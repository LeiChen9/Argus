"""底层工具：只放 IO 与.env 读取，不含任何业务。

- read_env_key: 从项目根 .env 读 key
- ENDPOINTS + MODEL_CHAIN: 模型容灾链的唯一事实源
- call_llm / call_llm_stream: 离线入口（同步签名，openai SDK 传输）
- call_llm_async / call_llm_stream_async: Worker 入口（js.fetch 传输）
- clean_llm_json: 去 markdown 代码块后解析 JSON

**两套传输、一条链**：openai SDK 依赖 httpx→socket，pyodide 装不了，Worker 侧
LLM 调用必须走 js.fetch；而 fetch 是 async，于是链主循环是 async 的，SDK 只是
被包了一层同步外壳。离线脚本和本地 uvicorn 仍调同步入口（asyncio.run 包装，
语义不变），Worker 侧 chat 调 async 入口（见 C 切片）。chain 逻辑（顺序、pinned、
token 闸门、失败转移）只有一份，不存在两套链对不上的问题。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path

from chinese_calendar import is_holiday
from markdown_it import MarkdownIt

logger = logging.getLogger("argus.llm")

GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


_MD = MarkdownIt("commonmark", {"html": False, "linkify": True})
_MD.enable("strikethrough")


def project_root() -> Path:
    """backend/ 的父目录，即项目根（.env 所在）。"""
    return Path(__file__).resolve().parents[1]


def read_env_key(name: str) -> str:
    """从项目根 .env 读 key。key 不入库（.env 已 gitignore）。"""
    for line in (project_root() / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip("'").strip('"')
    raise RuntimeError(f".env 缺少 {name}")


@cache
def llm_client() -> OpenAI:
    """Gemini 的 OpenAI 兼容端点。"""
    # openai 在函数内 import：pyodide 装不了它（依赖 httpx→socket）。Worker 侧
    # 走 fetch 传输，永远不进这个工厂；离线脚本照旧。
    from openai import OpenAI

    ep = ENDPOINTS["gemini"]
    return OpenAI(api_key=read_env_key(ep["key"]), base_url=ep["base_url"])


@cache
def deepseek_client() -> OpenAI:
    """DeepSeek 兜底端点。非开放时段见 deepseek_open。"""
    from openai import OpenAI

    ep = ENDPOINTS["deepseek"]
    return OpenAI(api_key=read_env_key(ep["key"]), base_url=ep["base_url"])


@cache
def agnes_client() -> OpenAI:
    """Agnes 免费端点。"""
    from openai import OpenAI

    ep = ENDPOINTS["agnes"]
    return OpenAI(api_key=read_env_key(ep["key"]), base_url=ep["base_url"])


@cache
def groq_client() -> OpenAI:
    """Groq 免费端点。本地直连会被 403，离线脚本记得走系统代理。"""
    from openai import OpenAI

    ep = ENDPOINTS["groq"]
    return OpenAI(api_key=read_env_key(ep["key"]), base_url=ep["base_url"])


# Groq 免费层输入上限 8000 token/分钟，超了直接 413。crawler 那种 2 万 token 的
# 抽取请求会被 Groq 连拒三次再降级到 Gemini，白等约 1 秒——按 token 数提前跳过。
GROQ_MAX_INPUT_TOKENS = 7000


# ── 端点表 ────────────────────────────────────────────────────────────────
# base_url / key / secret 名的唯一事实源。key 是离线 .env 里的名字（read_env_key），
# env 是 Worker 侧 wrangler secret 名。加一家端点只改这里 + MODEL_CHAIN 一行。
ENDPOINTS = {
    "gemini": {"base_url": GEMINI_BASE_URL, "key": "gemini_apiKey", "env": "GEMINI_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1/", "key": "deepseek_apiKey", "env": "DEEPSEEK_API_KEY"},
    "agnes": {"base_url": "https://apihub.agnes-ai.com/v1/", "key": "agnes_apiKey", "env": "AGNES_API_KEY"},
    "groq": {"base_url": "https://api.groq.com/openai/v1/", "key": "groq_apiKey", "env": "GROQ_API_KEY"},
}


def _input_tokens(messages: list[dict], tools: list[dict] | None) -> int:
    """估算输入 token 数。tiktoken 装不进 pyodide（Rust 扩展），换字符启发式。

    两个用途都是闸门不是账单：Groq 的 max_input_tokens 跳过、compact 的 128k
    阈值。西文约 4 字符/token、CJK 约 1 字/token，刻意高估——低估会把超窗请求
    放进去被 provider 拒，高估只是提前跳过一个模型，不改变链的正确性。
    """
    def est(s: str) -> int:
        # 逐字符数 CJK 是 Python 循环：chat 的 system prompt + 工具 schema 每步
        # 几万字符，pyodide 里每字符一次迭代会把免费档 10ms CPU 烧穿（线上实测
        # 1101）。改成一次 C 级 encode：ASCII 字符数即非 CJK 部分，余下是 CJK。
        ascii_len = len(s.encode("ascii", errors="ignore"))
        return (len(s) - ascii_len) + ascii_len // 4

    total = sum(est(m.get("content") or "") for m in messages)
    if tools:
        total += est(json.dumps(tools, ensure_ascii=False))
    return total


# ── DeepSeek 开放时段 ──────────────────────────────────────────────────────
# DeepSeek 不是 7×24 可用：北京时间周一至周五（法定节假日除外）9:00-12:00、
# 14:00-18:00 为高峰，峰段调用会被限流。先判时段再入链，而不是失败后重试。
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_PEAK_HOURS = frozenset(range(9, 12)) | frozenset(range(14, 18))


def deepseek_open(now: datetime | None = None) -> bool:
    """DeepSeek 现在开放吗：非工作日全天开放，周一至周五避开峰段。

    依据 DeepSeek 计价说明：调休上班的周末与中国法定节假日全天按空闲时段计费。
    周末无论是否补班都算这一类——chinese_calendar 把补班周六记成工作日，只认
    is_holiday 会把它错判成普通工作日。峰段因此只作用于周一至周五。

    节假日认 chinese_calendar：法定假期的周日算节假日，手写 weekday() 判断会
    判错。
    """
    # 峰段是北京时间，而 Worker 里 datetime.now() 落在 UTC——不显式钉 UTC+8 的话，
    # 线上判断的峰段会比真实错移 8 小时。离线（本机 CST）钉了也不变。
    now = now or datetime.now(timezone(timedelta(hours=8)))
    if is_holiday(now.date()) or now.weekday() >= 5:
        return True
    return now.hour not in DEEPSEEK_PEAK_HOURS


# 模型链：按优先级排序。DeepSeek 缺 key 或不在开放时段内不入链。
#
# 2026-10-16 清出两个死条目（线上实测）：nemotron 100% 挂请求（收了不吐字节，
# 每步白等 20s 超时）；ling 在 kilo 上已成付费模型（402 Credits Required）。
# 链从 8 条缩到 6 条，每一步的失败成本从 ~21s 降到毫秒级。
MODEL_CHAIN = [
    {"name": "agnes-3.0-flash", "endpoint": "agnes"},
    {"name": "openai/gpt-oss-120b", "endpoint": "groq", "max_input_tokens": GROQ_MAX_INPUT_TOKENS},
    {"name": "openai/gpt-oss-20b", "endpoint": "groq", "max_input_tokens": GROQ_MAX_INPUT_TOKENS},
    {"name": "qwen/qwen3.8-27b", "endpoint": "groq", "max_input_tokens": GROQ_MAX_INPUT_TOKENS},
    {"name": GEMINI_MODEL, "endpoint": "gemini"},
    {"name": DEEPSEEK_MODEL, "endpoint": "deepseek"},
]


# chat（带工具的主 agent）只走这几家。链首小模型带 tools 会每步都调工具、四步跑满
# 落不下正文（tech_doc 实测 126s 空回复）；groq 的 token 上限只适合不带工具的
# subagent 调用（compact / analyze_jd / 抽 persona）。见 _run_chain 的 allow_endpoints。
CHAT_ENDPOINTS = frozenset({"gemini", "agnes", "deepseek"})


# ── Worker 侧 bindings 注入 ───────────────────────────────────────────────
# entrypoint_worker 模块加载时注入 self.env（等价物）。Worker 里没有 /session/.env，
# read_env_key 读不到任何 key，所有 Worker 侧取 key 都走这里。离线永不注入。


_WORKER_ENV = None


def bind_worker_env(env) -> None:
    """entrypoint_worker 加载时调一次（每 isolate）。离线不调。"""
    global _WORKER_ENV
    _WORKER_ENV = env


def _worker_key(endpoint: str) -> str:
    """Worker 侧从 bindings 读 key。secret 名见 ENDPOINTS[endpoint]["env"]。"""
    if _WORKER_ENV is None:
        raise RuntimeError("Worker env 未注入（entrypoint_worker 没调 bind_worker_env？）")
    val = getattr(_WORKER_ENV, ENDPOINTS[endpoint]["env"], None)
    if not val:
        raise RuntimeError(f"Worker 缺 secret {ENDPOINTS[endpoint]['env']}（wrangler secret put {ENDPOINTS[endpoint]['env']}）")
    return str(val)


def active_chain() -> list[dict]:
    """当下真正可用的模型链。Worker 侧看 secret 在不在，离线侧看 .env。"""
    if _WORKER_ENV is not None:
        deepseek_usable = deepseek_open() and bool(
            getattr(_WORKER_ENV, ENDPOINTS["deepseek"]["env"], None))
    else:
        try:
            read_env_key("deepseek_apiKey")
            deepseek_usable = deepseek_open()
        except (RuntimeError, FileNotFoundError):
            deepseek_usable = False
    return [
        item
        for item in MODEL_CHAIN
        if item["name"] != DEEPSEEK_MODEL or deepseek_usable
    ]


def render_markdown(text: str) -> str:
    """LLM 回复里的 markdown 转 HTML，供前端气泡直接插。

    html=False：裸 <script>/<b> 一律转义成文本。LLM 会照抄简历里的文字，
    简历里若带标签不能变成可执行 HTML。链接仍走 markdown-it 的 URL 校验。
    """
    return _MD.render(text)


def clean_llm_json(raw: str) -> dict:
    import re
    body = raw.strip()
    if (body.startswith("```")):
        body = body.split("\n", 1)[1].rsplit("```", 1)[0].strip().removeprefix("json").strip()
    for _ in range(2):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            s, e = body.find("{"), body.rfind("}")
            if s >= 0 and e > s:
                body = body[s:e + 1]
            body = re.sub(r",\s*([}\]])", r"\1", body)
    return json.loads(body)


# ── 传输层 ────────────────────────────────────────────────────────────────
# 链主循环只认一个约定：await create(item, messages, tools, temperature,
# max_tokens, on_delta) -> {"content", "tool_calls"}。SDK 与 fetch 各自实现，
# 上行是唯一一条链。


def _chat_kwargs(tools, temperature, max_tokens, stream) -> dict:
    kw = {"temperature": temperature, "stream": stream}
    if tools:
        kw["tools"] = tools
    if max_tokens is not None:
        kw["max_tokens"] = max_tokens
    return kw


def _g(obj, name, default=None):
    """SDK 的 delta 对象与 fetch 解析出的 dict 都能读。"""
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


class _DeltaAcc:
    """流式增量累积。content 直接拼；tool_calls 按 index 分片到达（id 只在首片、
    name/arguments 后续分片追加），两套传输的 delta 结构同构，共用这一份。
    """

    def __init__(self):
        self.text = ""
        self.calls: dict[int, dict] = {}

    def add(self, d) -> str:
        """喂一个 delta，返回新增正文（空串表示这片只有工具调用）。"""
        new = _g(d, "content") or ""
        self.text += new
        for tc in _g(d, "tool_calls") or []:
            o = self.calls.setdefault(_g(tc, "index") or 0,
                                      {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if _g(tc, "id"):
                o["id"] = _g(tc, "id")
            fn = _g(tc, "function")
            if fn:
                if _g(fn, "name"):
                    o["function"]["name"] += _g(fn, "name")
                if _g(fn, "arguments"):
                    o["function"]["arguments"] += _g(fn, "arguments")
            # 透传 provider 的附加字段：Gemini 3 的 thought_signature 在
            # extra_content 里，下一步请求要原样带回，攒的时候丢了就 400。
            for k in ("extra_content", "thought_signature"):
                v = _g(tc, k)
                if v:
                    o[k] = v
        return new

    def result(self) -> list[dict] | None:
        return list(self.calls.values()) or None


_SDK_FACTORIES = {
    "gemini": llm_client,
    "deepseek": deepseek_client,
    "agnes": agnes_client,
    "groq": groq_client,
}


async def _sdk_create(item, messages, tools, temperature, max_tokens, on_delta=None) -> dict:
    """离线传输：openai SDK。同步调用包一层 async，让链主循环统一 await。

    tool_calls 的形状与从前逐字节一致（非流式是 SDK message 对象、流式是
    SimpleNamespace 列表）——chat.py 的消费端还没动，C2 统一成 dict。
    """
    stream = on_delta is not None
    resp = _SDK_FACTORIES[item["endpoint"]]().chat.completions.create(
        model=item["name"], messages=messages,
        **_chat_kwargs(tools, temperature, max_tokens, stream))
    if not stream:
        msg = resp.choices[0].message
        return {"content": msg.content, "tool_calls": msg.tool_calls}
    acc = _DeltaAcc()
    for ch in resp:
        new = acc.add(ch.choices[0].delta)
        if new:
            on_delta(new)
    # tool_calls 包回 SimpleNamespace：chat.py 的消费端按属性访问（t.function.name），
    # 与从前的形状逐字节一致。fetch 传输回 dict，C2 chat 上 Worker 时统一。
    from types import SimpleNamespace as NS
    calls = acc.result()
    ns_calls = [NS(id=c["id"], function=NS(name=c["function"]["name"],
                                           arguments=c["function"]["arguments"]))
                for c in calls] if calls else None
    return {"content": acc.text, "tool_calls": ns_calls}


async def _fetch_create(item, messages, tools, temperature, max_tokens, on_delta=None) -> dict:
    """Worker 传输：js.fetch 打 OpenAI 兼容端点。

    js / pyodide 的 import 在函数内：离线 CPython 里它们不存在，而本模块被离线
    脚本共享；离线永远不进这个函数，import 失败无从发生。
    """
    import js
    from pyodide.ffi import to_js
    from workers import fetch as js_fetch

    url = ENDPOINTS[item["endpoint"]]["base_url"] + "chat/completions"
    stream = on_delta is not None
    payload = json.dumps({"model": item["name"], "messages": messages,
                          **_chat_kwargs(tools, temperature, max_tokens, stream)})
    # 20s 兜底：上游挂住不返头时降级到链上下一个模型，而不是拖死整轮对话。
    # 只包住「等响应头」——流式响应本来就长，包全程会把正常长回答掐掉。
    # 20s 对链上所有模型都宽；kilo 的 nemotron 实测挂 30s，这条就是为它设的。
    try:
        resp = await asyncio.wait_for(js_fetch(url, method="POST", headers={
            "authorization": f"Bearer {_worker_key(item['endpoint'])}",
            "content-type": "application/json",
        }, body=payload), timeout=20.0)
    except asyncio.TimeoutError:
        raise RuntimeError(f"{item['name']} 20s 未响应")
    if resp.status != 200:
        raise RuntimeError(f"{item['name']} HTTP {resp.status}: {(await resp.text())[:200]}")
    if not stream:
        body_json = await resp.json()
        msg = body_json["choices"][0]["message"]
        return {"content": msg.get("content"), "tool_calls": msg.get("tool_calls"),
                "usage": body_json.get("usage")}
    reader = resp.body.getReader()
    decoder = js.TextDecoder.new()
    decode_stream = to_js({"stream": True})
    buf, acc = "", _DeltaAcc()
    while True:
        # 20s idle 超时：上游收了请求不吐字节（实测 kilo 的 nemotron 挂 30s 白等），
        # 没有这道闸门整轮对话就永远停在 reader.read() 上。超时按普通失败降级。
        # 20s 对链上所有模型都宽（groq <1s、gemini 1-3s、agnes ≤10s），
        # 而 chat/analyze 的 max_tokens=1024 也出不了需要更久的回答。
        try:
            chunk = await asyncio.wait_for(reader.read(), timeout=20.0)
        except asyncio.TimeoutError:
            raise RuntimeError(f"{item['name']} 流式 20s 无增量")
        if chunk.done:
            break
        buf += decoder.decode(chunk.value, decode_stream)
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return {"content": acc.text, "tool_calls": acc.result()}
            try:
                delta = json.loads(data)["choices"][0].get("delta") or {}
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                continue
            new = acc.add(delta)
            if new:
                on_delta(new)
    return {"content": acc.text, "tool_calls": acc.result()}


# 链的最近尝试记录（模型 / 耗时 / 结果）。线上没有 wrangler tail 可视性
# （本地网络连不上 tail 端点），慢或挂时靠它定位是哪一家、卡在哪一步。
_last_trace: list[dict] = []

# 本次 isolate 生命周期内、每个模型成功接话时记的 token 用量。
# 累加在内存里、请求末由 entrypoint 落 R2（usage.json）：每步都写一次 R2
# 会把 I/O 翻倍，而 token 账本晚几百毫秒落盘没有任何影响。
_usage: dict[str, dict] = {}


def usage_snapshot() -> dict:
    """取走并清零本轮累加的用量。entrypoint 每请求末调。

    必须 copy 一份再清：直接返回 _usage 本身的话，下面 _usage.clear() 会把
    交给调用方的那个字典也清空——账本会静默变成永远为空。
    """
    out = {k: dict(v) for k, v in _usage.items()}
    _usage.clear()
    return out


_usage_flush = None


def bind_usage_flush(fn) -> None:
    """entrypoint 注入：async fn(snapshot) -> None，把累加的用量落 R2。"""
    global _usage_flush
    _usage_flush = fn


async def flush_usage() -> None:
    """把本轮用量交给注入的落盘函数。没注入就是只累加不落盘（离线脚本）。"""
    if _usage_flush is not None and _usage:
        try:
            await _usage_flush(usage_snapshot())
        except Exception as e:  # 账本写失败绝不能把用户的回答搞挂
            logger.warning(f"用量落盘失败: {e}")


def _note_usage(model: str, usage, input_tokens: int, out_chars: int) -> None:
    """记一次成功调用的 token 用量。

    provider 报了 usage 就用它；没报就估——输入沿用链上为 max_input_tokens 算好的
    那个估算值，输出按正文字数折（中英混排取 2 字 1 token）。宁可给个标注过的
    估算，也不为了精确给各家传 stream_options/include_usage：报错的字段会让
    整轮直接降级，代价远大于账本精度。
    """
    if usage:
        u_in = _g(usage, "prompt_tokens") or _g(usage, "input_tokens") or input_tokens
        u_out = _g(usage, "completion_tokens") or _g(usage, "output_tokens") or out_chars // 2
    else:
        u_in, u_out = input_tokens, out_chars // 2
    row = _usage.setdefault(model, {"calls": 0, "input": 0, "output": 0})
    row["calls"] += 1
    row["input"] += int(u_in or 0)
    row["output"] += int(u_out or 0)


def last_trace() -> list[dict]:
    return _last_trace[-12:]


async def _run_chain(create, messages: list[dict], *, tools=None, temperature=0.7,
                     pinned=None, max_tokens=None, on_delta=None, allow_endpoints=None) -> dict:
    """统一 LLM 调用，按 active_chain 顺序故障转移。返回消息内容与实际模型名。

    pinned 把指定模型提到链首，**只影响第一次尝试**：它失败仍照常降级到链上其余模型。
    用于写文案这种「模型强弱直接决定产出质量」的调用——链首那几个免费小模型写简历
    只会产出套话，让容灾链顺序决定这类调用的质量是不合适的。
    """
    chain = active_chain()
    if allow_endpoints is not None:
        chain = [i for i in chain if i["endpoint"] in allow_endpoints]
    if pinned:
        # pinned 提到链首并**去重**：MODEL_CHAIN 里本来就有它，不去重的话一轮里
        # 同一个模型会被试两次（pinned 位 + 自然位），失败成本翻倍。
        # pinned 不在链上（被时段闸门摘掉/手滑写错）就忽略，照常按链走。
        hit = next((i for i in chain if i["name"] == pinned), None)
        if hit:
            chain = [hit, *[i for i in chain if i["name"] != pinned]]
    last_err = None
    failures = []
    tokens = _input_tokens(messages, tools)
    for item in chain:
        model_name = item["name"]
        limit = item.get("max_input_tokens")
        if limit and tokens > limit:
            logger.info(f"跳过 {model_name}: 输入 {tokens} token 超过 {limit}")
            failures.append(f"{model_name}: 输入超限跳过")
            continue
        t0 = time.perf_counter()
        try:
            msg = await create(item, messages, tools, temperature, max_tokens, on_delta)
            # 200 但既没正文也没工具调用 = 这家给不出东西，按失败降级到链上下一个模型。
            if not (msg.get("content") or "").strip() and not msg.get("tool_calls"):
                raise RuntimeError("空响应（无正文、无工具调用）")
            _last_trace.append({"model": model_name, "ms": round((time.perf_counter() - t0) * 1000), "ok": True})
            _note_usage(model_name, msg.get("usage"), tokens, len(msg.get("content") or ""))
            logger.info(f"使用模型: {model_name}")
            return {**msg, "model": model_name}
        except Exception as e:
            last_err = e
            failures.append(f"{model_name}: {type(e).__name__}: {str(e)[:120]}")
            _last_trace.append({"model": model_name, "ms": round((time.perf_counter() - t0) * 1000),
                                "ok": False, "err": f"{type(e).__name__}: {str(e)[:120]}"})
            logger.warning(f"模型 {model_name} 失败: {e}")
    # 各家失败原因拼进错误里：链是黑盒的话，线上慢/挂时只能干猜。
    raise RuntimeError(f"所有模型均不可用: {last_err}｜经过: {'; '.join(failures)}")


def call_llm(messages: list[dict], *, tools=None, temperature=0.7,
             pinned=None, max_tokens=None) -> dict:
    """离线入口：SDK 传输，同步签名。语义见 _run_chain。"""
    return asyncio.run(_run_chain(_sdk_create, messages, tools=tools,
                                  temperature=temperature, pinned=pinned, max_tokens=max_tokens))


def call_llm_stream(messages: list[dict], on_delta, *, tools=None, temperature=0.7,
                    pinned=None, max_tokens=None) -> dict:
    """离线流式入口：SDK 传输，语义同 call_llm。"""
    return asyncio.run(_run_chain(_sdk_create, messages, tools=tools, temperature=temperature,
                                  pinned=pinned, max_tokens=max_tokens, on_delta=on_delta))


async def call_llm_async(messages: list[dict], *, tools=None, temperature=0.7,
                         pinned=None, max_tokens=None, allow_endpoints=None) -> dict:
    """Worker 入口：fetch 传输。chat 上 Worker 时换这个（C2）。"""
    return await _run_chain(_fetch_create, messages, tools=tools,
                            temperature=temperature, pinned=pinned, max_tokens=max_tokens,
                            allow_endpoints=allow_endpoints)


async def call_llm_stream_async(messages: list[dict], on_delta, *, tools=None, temperature=0.7,
                                pinned=None, max_tokens=None, allow_endpoints=None) -> dict:
    """Worker 流式入口：fetch 传输，语义同 call_llm_async。"""
    return await _run_chain(_fetch_create, messages, tools=tools, temperature=temperature,
                            pinned=pinned, max_tokens=max_tokens, on_delta=on_delta,
                            allow_endpoints=allow_endpoints)


def ask_json(prompt: str, blocks: list[str], temperature: float = 0.7,
             model: str | None = None, max_tokens: int | None = None) -> dict:
    """一次 LLM 调用要回 JSON。blocks 是跟在 prompt 后面的几段材料，各自一个 user 消息。

    model 非空时把它提到容灾链首（见 _run_chain 的 pinned）。
    """
    messages = [{"role": "user", "content": prompt},
                *({"role": "user", "content": b} for b in blocks)]
    return clean_llm_json(call_llm(messages, temperature=temperature, pinned=model, max_tokens=max_tokens)["content"])


async def ask_json_async(prompt: str, blocks: list[str], temperature: float = 0.7,
                         model: str | None = None, max_tokens: int | None = None) -> dict:
    """ask_json 的 Worker 版：fetch 传输。pinned 语义同 _run_chain。"""
    messages = [{"role": "user", "content": prompt},
                *({"role": "user", "content": b} for b in blocks)]
    msg = await _run_chain(_fetch_create, messages, temperature=temperature,
                           pinned=model, max_tokens=max_tokens)
    return clean_llm_json(msg["content"])

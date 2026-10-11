"""底层工具：只放 IO 与.env 读取，不含任何业务。

- read_env_key: 从项目根 .env 读 key
- llm_client / agnes_client / kilo_client / groq_client: 各家 OpenAI 兼容端点，chat 和 persona 共用
- active_chain / call_llm: 模型容灾链，按 active_chain 顺序故障转移
- clean_llm_json: 去 markdown 代码块后解析 JSON
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from pathlib import Path

from chinese_calendar import is_holiday
from markdown_it import MarkdownIt
from openai import OpenAI

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


SCRAPER_API_KEY = read_env_key("scraper_apiKey")


@cache
def llm_client() -> OpenAI:
    """Gemini 的 OpenAI 兼容端点。"""
    return OpenAI(
        api_key=read_env_key("gemini_apiKey"),
        base_url=GEMINI_BASE_URL,
    )


@cache
def deepseek_client() -> OpenAI:
    """DeepSeek 兜底端点。非开放时段见 deepseek_open。"""
    return OpenAI(
        api_key=read_env_key("deepseek_apiKey"),
        base_url="https://api.deepseek.com/v1/",
    )


@cache
def agnes_client() -> OpenAI:
    """Agnes 免费端点。"""
    return OpenAI(
        api_key=read_env_key("agnes_apiKey"),
        base_url="https://apihub.agnes-ai.com/v1/",
    )


@cache
def kilo_client() -> OpenAI:
    """Kilo 网关，托管 openrouter 的免费模型。模型名要写全，group 别名会解析到别的模型。"""
    return OpenAI(
        api_key=read_env_key("kilo_apiKey"),
        base_url="https://api.kilo.ai/api/gateway/",
    )


@cache
def groq_client() -> OpenAI:
    """Groq 免费端点。只能走系统代理，直连会被 403。"""
    return OpenAI(
        api_key=read_env_key("groq_apiKey"),
        base_url="https://api.groq.com/openai/v1/",
    )


# Groq 免费层输入上限 8000 token/分钟，超了直接 413。crawler 那种 2 万 token 的
# 抽取请求会被 Groq 连拒三次再降级到 Gemini，白等约 1 秒——按 token 数提前跳过。
GROQ_MAX_INPUT_TOKENS = 7000


@cache
def _token_counter():
    import tiktoken

    return tiktoken.get_encoding("o200k_base")


def _input_tokens(messages: list[dict], tools: list[dict] | None) -> int:
    """估算输入 token 数。o200k_base 对 Groq 的 tokenizer 是近似，闸门够用。"""
    enc = _token_counter()
    total = sum(len(enc.encode(m.get("content") or "")) for m in messages)
    if tools:
        total += len(enc.encode(json.dumps(tools, ensure_ascii=False)))
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
    now = now or datetime.now()
    if is_holiday(now.date()) or now.weekday() >= 5:
        return True
    return now.hour not in DEEPSEEK_PEAK_HOURS


# 模型链：按优先级排序。DeepSeek 缺 key 或不在开放时段内不入链。
MODEL_CHAIN = [
    {"name": "agnes-3.0-flash", "client": agnes_client},
    {"name": "inclusionai/ling-3.1-flash", "client": kilo_client},
    {"name": "nvidia/nemotron-3-ultra-550b-a55b:free", "client": kilo_client},
    {"name": "openai/gpt-oss-120b", "client": groq_client, "max_input_tokens": GROQ_MAX_INPUT_TOKENS},
    {"name": "openai/gpt-oss-20b", "client": groq_client, "max_input_tokens": GROQ_MAX_INPUT_TOKENS},
    {"name": "qwen/qwen3.8-27b", "client": groq_client, "max_input_tokens": GROQ_MAX_INPUT_TOKENS},
    {"name": GEMINI_MODEL, "client": llm_client},
    {"name": DEEPSEEK_MODEL, "client": deepseek_client},
]


def active_chain() -> list[dict]:
    """当下真正可用的模型链。"""
    try:
        read_env_key("deepseek_apiKey")
        deepseek_usable = deepseek_open()
    except RuntimeError:
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
    if body.startswith("```"):
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


def ask_json(prompt: str, blocks: list[str], temperature: float = 0.7,
             model: str | None = None) -> dict:
    """一次 LLM 调用要回 JSON。blocks 是跟在 prompt 后面的几段材料，各自一个 user 消息。

    model 非空时把它提到容灾链首（见 call_llm 的 pinned）。
    """
    messages = [{"role": "user", "content": prompt},
                *({"role": "user", "content": b} for b in blocks)]
    return clean_llm_json(call_llm(messages, temperature=temperature, pinned=model)["content"])


def call_llm(messages: list[dict], *, tools: list[dict] | None = None, temperature: float = 0.7,
              pinned: str | None = None) -> dict:
    """统一 LLM 调用，按 active_chain 顺序故障转移。返回 message 内容与实际使用的模型名。

    pinned 把指定模型提到链首，**只影响第一次尝试**：它失败仍照常降级到链上其余模型。
    用于写文案这种「模型强弱直接决定产出质量」的调用——链首那几个免费小模型写简历
    只会产出套话，让容灾链顺序决定这类调用的质量是不合适的。
    """
    import logging
    logger = logging.getLogger("argus.llm")
    chain = active_chain()
    if pinned:
        chain = sorted(chain, key=lambda item: item["name"] != pinned)
    last_err = None
    tokens = _input_tokens(messages, tools)
    for item in chain:
        model_name = item["name"]
        limit = item.get("max_input_tokens")
        if limit and tokens > limit:
            logger.info(f"跳过 {model_name}: 输入 {tokens} token 超过 {limit}")
            continue
        client = item["client"]()
        try:
            kwargs = {"model": model_name, "messages": messages, "temperature": temperature}
            if tools:
                kwargs["tools"] = tools
            resp = client.chat.completions.create(**kwargs)
            logger.info(f"使用模型: {model_name}")
            msg = resp.choices[0].message
            return {"content": msg.content, "tool_calls": msg.tool_calls, "model": model_name}
        except Exception as e:
            last_err = e
            logger.warning(f"模型 {model_name} 失败: {e}")
    raise RuntimeError(f"所有模型均不可用: {last_err}")

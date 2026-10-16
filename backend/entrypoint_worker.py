"""Cloudflare Worker 入口。

Slice A Spike 已验证：纯 Python 包进得了 pyodide、js.fetch 流式 SSE 通、R2 读写通、
免费 10ms CPU 扛得住读取路径。Slice B 起只读 API 在此扩展：数据请求先进 _refresh
灌 store，领域函数无感复用；C1 起 LLM 调用走 common 的 fetch 传输（/api/debug/llm
是它的验收与运维探针）。

路由仍在这个文件里。所有请求先过 access code：Worker 持有 LLM key，
不设防等于把六家的调用权公开。
"""

import api_chat
import api_read
import api_write
import asyncio
import common
import json
import secrets
from datetime import date
from urllib.parse import parse_qs, urlparse

import js
from js import performance
from pyodide.ffi import to_js
from workers import Response, WorkerEntrypoint, env as workers_env
from sessions import bind_r2 as bind_sessions
from utils import bind_store, bind_writer

# bindings 注入：模型 key 走 secret（Worker 里没有 /session/.env），
# 会话落 R2（chat_sessions/），数据文本灌 store，领域写经 writer 落 R2。
common.bind_worker_env(workers_env)
bind_sessions(workers_env)


async def _write_r2(key: str, text: str) -> None:
    """utils 写通道的 Worker 实现：领域模块的 save_file_async 经这里落 R2。"""
    await workers_env.DATA.put(key, text)


bind_writer(_write_r2)

ACCESS_HEADER = "x-access-code"
PROBE_KEY = "_spike/probe.json"

# _refresh 拉的三个单文件 + resumes/ 前缀下的全部简历。合计 <300KB。
STORE_KEYS = ("careers.json", "boss_jobs.json", "persona.json")
RESUME_PREFIX = "resumes/"


def _ms(t0: float) -> float:
    # pyodide 的 time.perf_counter 精度不够（亚毫秒步进全是 0.0），改用 JS 的
    # performance.now()：µs 级，且与 CPU 计费口径一致（墙钟扣掉 I/O 等待）。
    return performance.now() - t0


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _authorized(request, env) -> bool:
    """access code 校验。secret 缺失时一律拒绝——宁可在 dev 里吵，不要裸奔上线。"""
    try:
        expected = env.ACCESS_CODE
    except AttributeError:
        return False
    if not expected:
        return False
    given = request.headers.get(ACCESS_HEADER) or ""
    if not given:
        given = parse_qs(urlparse(request.url).query).get("code", [""])[0]
    return secrets.compare_digest(given, expected)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if not _authorized(request, self.env):
            return Response.json({"detail": "access code 不对"}, status=401)
        path = urlparse(request.url).path
        if path == "/api/ping":
            return await self._ping(request)
        if path == "/api/debug/llm":
            return await self._debug_llm(request)
        if path.startswith("/api/"):
            await self._refresh()
            if path.startswith("/api/chat"):
                try:
                    return await api_chat.dispatch(path, request)
                except api_chat.Bad as e:
                    return Response.json({"detail": e.detail}, status=e.status)
            if path == "/api/persona/init" or path == "/api/persona/targets":
                try:
                    if path == "/api/persona/init":
                        return await api_write.persona_init(request)
                    return await api_write.persona_targets(request)
                except api_write.Bad as e:
                    return Response.json({"detail": e.detail}, status=e.status)
            if path.startswith("/api/resumes/") and path.endswith("/edits"):
                cid = path[len("/api/resumes/"):-len("/edits")]
                try:
                    return await api_write.resume_edits(cid, request)
                except api_write.Bad as e:
                    return Response.json({"detail": e.detail}, status=e.status)
            if path == "/api/jobs":
                return api_read.jobs_list()
            if path == "/api/careers":
                return api_read.careers_list()
            if path == "/api/persona":
                return api_read.persona_get()
            if path == "/api/me":
                return api_read.me()
            if path == "/api/resumes":
                return await api_read.resumes_list_ensured()
            if path.startswith("/api/resumes/"):
                return api_read.resumes_get(path[len("/api/resumes/"):])
        return Response.json({"detail": f"没有 {path}"}, status=404)

    async def _refresh(self) -> None:
        """每数据请求前从 R2 拉全量文本灌 store。

        全量而非按需：三个单文件 + 几份简历合计 <300KB，一轮 list + 一轮并行
        get，I/O 约 200-300ms（不计 CPU），换来领域函数零改造复用。单用户、
        写路径未开，不存在读到旧快照的一致性问题——唯一的写方就是 Worker 自己。
        """
        async def _text(body):
            return None if body is None else await body.text()

        listed = await self.env.DATA.list(to_js({"prefix": RESUME_PREFIX}))
        resume_keys = [obj.key for obj in listed.objects]
        keys = (*STORE_KEYS, *resume_keys)
        bodies = await asyncio.gather(*[self.env.DATA.get(k) for k in keys])
        texts = await asyncio.gather(*[_text(b) for b in bodies])
        bind_store({k: t for k, t in zip(keys, texts) if t is not None})

    async def _ping(self, request) -> Response:
        """读真实数据文件并分步计时。R2 往返是 I/O 不计 CPU，其余步骤墙钟≈CPU。"""
        steps = {}

        t0 = performance.now()
        careers_obj = await self.env.DATA.get("careers.json")
        if careers_obj is None:
            return Response.json({"detail": "R2 缺 careers.json，先传快照"}, status=500)
        careers_text = await careers_obj.text()
        steps["r2_get_careers_ms"] = _ms(t0)

        # 校准先行：已知成本的纯 Python 循环。读数为 0 说明时钟被量化了，
        # 后面所有亚毫秒数字都不可信；量级对得上（pyodide 里此 loop 约 10-30ms）
        # 才说明「解析 ≈ 0ms」是真快，不是没测到。
        # loops 可调大把信号顶出量化区间；20M 级能返回即说明不在免费 CPU 限额内。
        loops = int(parse_qs(urlparse(request.url).query).get("loops", ["200000"])[0])
        t0 = performance.now()
        acc = 0
        for i in range(loops):
            acc += i
        steps["calib_loop_ms"] = _ms(t0)

        # 解析放大 100 倍取均值：单次亚毫秒时，一次测量的分辨率噪声比信号大。
        t0 = performance.now()
        for _ in range(100):
            careers = json.loads(careers_text)
        steps["parse_careers_ms"] = (performance.now() - t0) / 100

        t0 = performance.now()
        jobs_text = await (await self.env.DATA.get("boss_jobs.json")).text()
        steps["r2_get_jobs_ms"] = _ms(t0)

        t0 = performance.now()
        for _ in range(100):
            jobs = json.loads(jobs_text)
        steps["parse_jobs_ms"] = (performance.now() - t0) / 100

        # import 与渲染分开计：冷 isolate 首请求要付 import，那笔也算 CPU。
        t0 = performance.now()
        from markdown_it import MarkdownIt
        steps["import_markdown_it_ms"] = _ms(t0)

        t0 = performance.now()
        md = MarkdownIt("commonmark", {"html": False})
        for _ in range(100):
            md.render(careers_text[:3000])
        steps["render_3k_ms"] = (performance.now() - t0) / 100

        t0 = performance.now()
        from chinese_calendar import is_holiday
        steps["import_chinese_calendar_ms"] = _ms(t0)

        t0 = performance.now()
        holiday = is_holiday(date.today())
        steps["is_holiday_ms"] = _ms(t0)

        t0 = performance.now()
        await self.env.DATA.put(PROBE_KEY, json.dumps({"ok": True}))
        back = await self.env.DATA.get(PROBE_KEY)
        await self.env.DATA.delete(PROBE_KEY)
        steps["r2_put_get_delete_ms"] = _ms(t0)

        cpu_bound = {k: v for k, v in steps.items() if "r2_" not in k}
        return Response.json({
            "steps": {k: round(v, 2) for k, v in steps.items()},
            "cpu_bound_ms": round(sum(cpu_bound.values()), 2),
            "chain_trace": common.last_trace(),
            "careers_count": len(careers.get("careers", [])),
            "jobs_count": len(jobs.get("jobs", {})),
            "today_is_holiday": holiday,
            "probe_roundtrip_ok": back is not None,
        })

    async def _debug_llm(self, request) -> Response:
        """C1 验收载体 + 常驻运维探针：在 Worker 里真实跑一遍容灾链。

        POST /api/debug/llm {"messages":[...], "model":"(可选 pinned)", "stream":true}
        非流式返回命中的模型与内容；流式走 SSE（发送协程与链并行——on_delta 是
        同步回调，只往队列里塞，真正写流是另一件事）。chat 上线后这个端点留着：
        换模型、验某家 endpoint 通不通，都不用等前端。
        """
        body = await request.json()
        messages = body.get("messages") or [{"role": "user", "content": "用一句话说明你是哪家模型"}]
        model = body.get("model")
        tools = body.get("tools")
        if body.get("stream"):
            return await self._debug_llm_stream(messages, model)
        msg = await common.call_llm_async(messages, tools=tools, pinned=model, max_tokens=8192)
        return Response.json({"model": msg["model"], "content": msg["content"],
                              "tool_calls": bool(msg.get("tool_calls"))})

    async def _debug_llm_stream(self, messages, model) -> Response:
        ts = js.TransformStream.new()
        writer = ts.writable.getWriter()
        # 先返回响应，内容边算边流。客户端断开时 writer.write 会抛，由 finally 收尾。
        resp = Response(ts.readable, headers={
            "content-type": "text/event-stream",
            "cache-control": "no-store",
            "x-accel-buffering": "no",
        })

        async def pump():
            q: asyncio.Queue = asyncio.Queue()

            def on_delta(t):
                q.put_nowait(t)

            async def sender():
                while True:
                    t = await q.get()
                    if t is None:
                        return
                    await writer.write(_sse("content", {"content": t}))

            send_task = asyncio.create_task(sender())
            try:
                msg = await common.call_llm_stream_async(
                    messages, on_delta, pinned=model, max_tokens=8192)
                await q.put(None)
                await send_task
                await writer.write(_sse("reply", {"model": msg["model"]}))
            except Exception as e:
                await q.put(None)
                await send_task
                await writer.write(_sse("error", {"detail": str(e)[:300]}))
            finally:
                await writer.close()

        asyncio.create_task(pump())
        return resp

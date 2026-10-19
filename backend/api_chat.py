"""Worker 侧 chat HTTP 层：路由表入口调的这几个端点。

领域逻辑全在 chat.py（agent loop、工具注册、会话）；这里只做 HTTP 边界的事：
取 sid、解 body、拼 SSE。SSE 的 5s 心跳是保命线——原 chat.py::chat_stream 的注释：
运营商 NAT 会把长时间没有字节的连接当空闲掐掉，客户端报 Load failed，而后端
早把答案算完存盘了。Worker 没有线程，对应物是 TransformStream + 发送协程。
"""

import asyncio
import json
import re

import js

import common
import sessions
from chat import (
    answer, history, undo, full_history,
    session_list, delete_session,
)
from workers import Response

SESSION_HEADER = "x-session-id"


class Bad(Exception):
    """HTTP 边界错误（400/404）。entrypoint 接住它转成 JSON 响应。"""

    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def _sid(request) -> str:
    raw = (request.headers.get(SESSION_HEADER) or "").strip() or "default"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)[:64] or "default"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _message(request) -> str:
    try:
        body = await request.json()
    except Exception:
        raise Bad("请求体不是合法 JSON")
    msg = (body.get("message") or "").strip()
    if not msg:
        raise Bad("消息为空")
    return msg


async def _target_sid(request) -> str:
    """删除端点要删哪个会话由 body 里的 sid 指定（不能复用 header 的默认兜底：
    缺 header 会退成 "default"，那是别人的会话）。"""
    try:
        body = await request.json()
    except Exception:
        raise Bad("请求体不是合法 JSON")
    sid = (body.get("sid") or "").strip()
    if not sid:
        raise Bad("缺少 sid")
    return re.sub(r"[^a-zA-Z0-9_-]", "_", sid)[:64]


async def chat(request) -> Response:
    sid = _sid(request)
    message = await _message(request)
    try:
        payload = await answer(sid, message)
        # 带上链上各次尝试的耗时与结果：线上排障全靠它（wrangler tail 本地连不上，
        # 走代理连上也很笨）。命中的模型在 _finish 的响应里（model 字段）。
        # 前端忽略多余字段。
        payload["chain"] = common.last_trace()
        payload["session_backend"] = sessions.backend_name()
        return Response.json(payload)
    except RuntimeError:
        # 所有模型均不可用/模型没产出正文。链上细节只进 trace，不给用户看。
        return Response.json({"detail": "暂时连不上模型，过会儿再试"}, status=502)


async def chat_stream(request) -> Response:
    sid = _sid(request)
    message = await _message(request)
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
            q.put_nowait(("content", {"content": t}))

        async def sender():
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    await writer.write(": keepalive\n\n")
                    continue
                if item is None:
                    return
                await writer.write(_sse(*item))

        send_task = asyncio.create_task(sender())
        try:
            await q.put(("reply", await answer(sid, message, on_delta=on_delta)))
        except Exception:
            # 内部错误（含整条链失败）不给用户看细节，链上有 last_trace 可查。
            await q.put(("error", {"detail": "暂时连不上模型，过会儿再试"}))
        finally:
            await q.put(None)
            await send_task
            await writer.close()

    asyncio.create_task(pump())
    return resp


async def chat_sessions(request) -> Response:
    """侧栏：当前用户的会话摘要列表（sid/title/updated_at）。"""
    return Response.json(await session_list())


async def chat_delete(request) -> Response:
    """删掉一个会话，R2 上的对象同步删除。body {"sid": "..."}。"""
    return Response.json(await delete_session(await _target_sid(request)))


async def chat_history(request) -> Response:
    return Response.json(await history(_sid(request)))


async def chat_messages(request) -> Response:
    return Response.json(await full_history(_sid(request)))


async def chat_undo(request) -> Response:
    return Response.json(await undo(_sid(request)))


async def dispatch(path: str, request) -> Response:
    """entrypoint 的 chat 段路由表。"""
    if path == "/api/chat":
        return await chat(request)
    if path == "/api/chat/stream":
        return await chat_stream(request)
    if path == "/api/chat/sessions":
        return await chat_sessions(request)
    if path == "/api/chat/delete":
        return await chat_delete(request)
    if path == "/api/chat/history":
        return await chat_history(request)
    if path == "/api/chat/messages":
        return await chat_messages(request)
    if path == "/api/chat/undo":
        return await chat_undo(request)
    raise Bad(f"没有 {path}", status=404)

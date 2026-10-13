from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from common import project_root, render_markdown, call_llm, call_llm_stream
from utils import load_file
from tools import (
    auto_compact, read_persona, read_careers, read_gaps_index, read_gap, search_jobs,
    start_resume, read_resume, critique_resume, analyze_jd,
)
from persona import get_persona, init_persona_from_text, read_upload, save_targets
from resume import (
    DIRECTIVE,
    RESUME_DIR,
    apply_edits,
    body as resume_body,
    document,
    ensure_all,
)

logger = logging.getLogger("argus.chat")

router = APIRouter()

SYSTEM_PROMPT = """你是 Argus，一个职业发展助手。

你的目标是充分了解用户，为他/她找到心仪合适的工作。
通过持续对话理解用户经历，用户求职的目标，期望薪资范围，以及期望工作城市。

你对用户的了解全部存在四个只读文件里，需要时自己判断读哪个，不要预读、也不要一次读全：
read_persona（**他最初上传的那份**履历与求职意向）、read_careers（岗位侧要什么能力）、
read_job_gaps（哪些岗位已有差距解读）、read_job_gap（某个岗位差在哪）。
先用 read_persona 确认用户底细，再用 read_careers 看岗位要求，最后才用 read_job_gap 核对具体岗位。

读完直接回答用户关心的事，不要罗列你读了哪些文件、也不要复述文件里的原始结构。
每次只输出一两句话。不要长篇大论。

用户**贴来一份岗位 JD**时，调 analyze_jd 判断是否合适，并把开场白一并给他。

**简历**：用户想为某个职能准备简历时（不管是他说「我想投经营分析」还是「帮我改改简历」），
你自己判断该针对哪个职能，调 start_resume 开始跟他聊——不要问用户要点哪个按钮。
简历**由用户自己在 Resume 页亲手改**，你不要替他写，也不要问要不要帮他写。"""

SESSION_TTL = 7 * 24 * 3600
_sessions: dict[str, dict] = {}


def _session_file(sid: str) -> Path:
    return project_root() / "data" / "chat_sessions" / f"{sid}.json"


def _sid(request: Request) -> str:
    raw = (request.headers.get("x-session-id") or "").strip() or "default"
    sid = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)[:64] or "default"
    return sid


def _load_session(sid: str) -> dict:
    now = time.time()
    if sid in _sessions:
        s = _sessions[sid]
        if now - s.get("updated_at", 0) > SESSION_TTL:
            s["history"] = []
            s["resume_career"] = None
            s["updated_at"] = now
            _save_session(sid)
        return s
    p = _session_file(sid)
    if p.exists():
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
            if now - s.get("updated_at", 0) <= SESSION_TTL:
                _sessions[sid] = s
                return s
            p.unlink(missing_ok=True)
        except Exception:
            pass
    s = {"history": [], "resume_career": None, "updated_at": now}
    _sessions[sid] = s
    return s


def _save_session(sid: str) -> None:
    s = _sessions.get(sid)
    if not s:
        return
    s["updated_at"] = time.time()
    p = _session_file(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _current_resume(sid: str) -> dict | None:
    sess = _load_session(sid)
    rc = sess.get("resume_career")
    return load_file(RESUME_DIR / f"{rc}.json") if rc else None


def _system_prompt(sid: str) -> str:
    saved = _current_resume(sid)
    if not saved:
        return SYSTEM_PROMPT
    stamp = f"最后由用户自己修改于 {saved.get('updated_at', '未知时间')}"
    return "\n\n".join([
        SYSTEM_PROMPT,
        DIRECTIVE.format(career=saved["career_name"]),
        f"## 当前简历（{saved['career_name']}，{stamp}）\n\n{resume_body(saved)}\n\n"
        "上面是磁盘上的当前版本，**他随时可能刚在 Resume 页改过**。你在这段对话里读到的、"
        "自己记下的任何简历内容一律作废，以这一份为准。",
    ])


class ChatRequest(BaseModel):
    message: str


class TargetRequest(BaseModel):
    target: list[str] = Field(default_factory=list)
    target_base: str = ""
    target_salary: str = ""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_persona",
            "description": "读用户最初上传的那份履历与求职意向：工作经历、项目、技能，以及意向职位/城市/薪资。凡是问到用户是谁、做过什么、能投哪，先读这个。注意这不是他在 Resume 页改过的当前版本，两份会分叉。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_careers",
            "description": "读岗位侧的 Career 定义：每个 Career 的定位、岗位归属判据、要求的能力清单（分 core/important/bonus）及成员岗位。用户问某类岗位要什么能力、或这几个岗位像不像一类时读。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_job_gaps",
            "description": "读岗位 × 用户差距解读的索引：公司、岗位、薪资、地点，约 30 条。只列清单不展开，先读它才知道有哪些岗位值得细看。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_job_gap",
            "description": "读单个岗位的完整差距解读。job_id 取自 read_job_gaps 的索引。返回每条要求的匹配状态（transferable/gap）、缺什么、简历里哪一段作证据，以及当时的求职意向。用户关心某个具体岗位值不值得投时才读。",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "岗位 id，来自 read_job_gaps"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_jd",
            "description": "用户贴来一份岗位 JD 时调它：对比他的 Persona 判断这个岗位是否合适，并给出一段招聘平台上打招呼的开场白。JD 原文从用户消息里取，原样传入，不要自己编。",
            "parameters": {
                "type": "object",
                "properties": {"jd": {"type": "string", "description": "用户贴来的岗位 JD 原文"}},
                "required": ["jd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_resume",
            "description": "开始为某个职能准备简历。这个职能还没有简历时，会按他自己传的那份履历（去掉求职意向）建一份底稿。返回该职能的定位与能力要求、以及他现有材料的提纲，够你据此开始提问。用户想投某个职能时调它，不要问用户要点哪个按钮。简历之后由他自己去 Resume 页改，你不碰它。",
            "parameters": {
                "type": "object",
                "properties": {"career_id": {"type": "string", "description": "career_id，来自 read_careers"}},
                "required": ["career_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_resume",
            "description": "读当前简历全文，也就是他在 Resume 页改过的那一份。只读——你没有任何修改它的工具。",
            "parameters": {
                "type": "object",
                "properties": {"career_id": {"type": "string", "description": "career_id"}},
                "required": ["career_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "critique_resume",
            "description": "筛简历。以招聘方视角判断这份简历够不够吸引他、会不会进面试。返回可改的地方（fixable，带 path）和只能继续挖的缺口（needs_mining）。结论和建议要讲给他听，由他自己去改——你只评，不写。",
            "parameters": {
                "type": "object",
                "properties": {"career_id": {"type": "string", "description": "career_id"}},
                "required": ["career_id"],
            },
        },
    },
]


READERS = {
    "read_persona": read_persona,
    "read_careers": read_careers,
    "read_job_gaps": read_gaps_index,
    "read_job_gap": read_gap,
    "analyze_jd": analyze_jd,
}

RESUME_TOOLS = {
    "start_resume": start_resume,
    "read_resume": read_resume,
    "critique_resume": critique_resume,
}


MAX_TOOL_STEPS = 4


def _execute_tool(sid: str, name: str, args: dict) -> tuple[dict, list[dict] | None]:
    if name in READERS:
        return READERS[name](**args), None
    if name in RESUME_TOOLS:
        result = RESUME_TOOLS[name](**args)
        if name == "start_resume" and result.get("status") == "ok":
            _load_session(sid)["resume_career"] = args["career_id"]
        return result, None
    if name == "update_persona":
        save_targets(args["target"], args["target_base"], args["target_salary"])
        return {"status": "ok"}, None
    if name == "search_jobs":
        return search_jobs(args["keyword"])
    return {"status": "error", "detail": f"没有 {name} 这个工具"}, None


def _run_agent(sid: str, messages: list[dict]) -> tuple[dict, list[dict] | None]:
    cards = None
    for _ in range(MAX_TOOL_STEPS):
        msg = call_llm(messages, tools=TOOLS, max_tokens=8192)
        if not msg["tool_calls"]:
            return msg, cards
        messages.append({"role": "assistant", "content": msg["content"], "tool_calls": [t.model_dump(exclude_none=True) for t in msg["tool_calls"]]})
        for t in msg["tool_calls"]:
            result, found = _execute_tool(sid, t.function.name, json.loads(t.function.arguments))
            cards = found or cards
            messages.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps(result, ensure_ascii=False)})
    return msg, cards


def _run_agent_stream(sid: str, messages: list[dict], on_delta) -> tuple[dict, list[dict] | None]:
    cards = None
    for _ in range(MAX_TOOL_STEPS):
        msg = call_llm_stream(messages, on_delta, tools=TOOLS, max_tokens=8192)
        if not msg["tool_calls"]: return msg, cards
        tc = [{"id": t.id, "type": "function", "function": {"name": t.function.name, "arguments": t.function.arguments}} for t in msg["tool_calls"]]
        messages.append({"role": "assistant", "content": msg["content"], "tool_calls": tc})
        for t in msg["tool_calls"]:
            r, f = _execute_tool(sid, t.function.name, json.loads(t.function.arguments or "{}"))
            cards = f or cards
            messages.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps(r, ensure_ascii=False)})
    return msg, cards


def _messages(sid: str, message: str) -> list[dict]:
    """一轮对话要发给模型的消息。流式和非流式共用。"""
    sess = _load_session(sid)
    return [
        {"role": "system", "content": _system_prompt(sid)},
        *auto_compact(sess["history"]),
        {"role": "user", "content": message},
    ]


def _finish(sid: str, message: str, msg: dict, cards: list | None) -> dict:
    """把这一轮落进会话并拼出响应。落盘在拼响应之前，响应丢了也还能捞回来。"""
    sess = _load_session(sid)
    reply = msg["content"] or ""
    sess["history"].append({"role": "user", "content": message})
    sess["history"].append({"role": "assistant", "content": reply})
    _save_session(sid)
    resp = {"reply": render_markdown(reply)}
    if cards:
        resp["jobs"] = cards
    card = _resume_card(sid)
    if card:
        resp["resume"] = card
    return resp


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# 心跳是这个端点存在的理由：agent loop 在线程里跑，主线程每 5 秒吐一个 SSE 注释行。
# 
# 跑一轮要 30-90 秒，这期间一个字节都不发的话，流量网络上的运营商 NAT 会把这条
# 连接当空闲掐掉，Safari 报 Load failed，而后端早把答案算完存盘了（真发生过）。
# 注释行在 SSE 里合法、客户端会忽略，正是用来保活的。心跳不携带任何内容。
@router.post("/api/chat/stream")
def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息为空")
    sid = _sid(request)
    messages = _messages(sid, message)
    out: queue.Queue = queue.Queue()

    def work():
        def on_delta(t): out.put(("content", {"content": t}))
        try:
            out.put(("reply", _finish(sid, message, *_run_agent_stream(sid, messages, on_delta))))
        except Exception as e:
            out.put(("error", {"detail": str(e)}))

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while True:
            try:
                kind, payload = out.get(timeout=5)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            yield _sse(kind, payload)
            if kind in ("reply", "error"): return

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/api/chat")
def chat(body: ChatRequest, request: Request) -> dict:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息为空")
    sid = _sid(request)
    try:
        msg, cards = _run_agent(sid, _messages(sid, message))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return _finish(sid, message, msg, cards)


def _resume_card(sid: str) -> dict | None:
    saved = _current_resume(sid)
    return document(_load_session(sid)["resume_career"]) if saved else None


@router.post("/api/chat/clear")
def chat_clear(request: Request) -> dict:
    sid = _sid(request)
    sess = _load_session(sid)
    n = len(sess["history"])
    sess["history"].clear()
    mode = sess["resume_career"]
    sess["resume_career"] = None
    _save_session(sid)
    return {"cleared": n, "resume_career": mode}


@router.get("/api/chat/history")
def chat_history(request: Request) -> dict:
    """最后一轮对话，用来在请求被掐断后把已经算完的答案取回来。

    请求失败不代表这一轮没跑完——切走 App、运营商断流都是客户端单方面取消，
    后端照跑完并存了盘（_save_session 在拼响应之前）。此时界面只能显示一句
    Load failed，答案却躺在会话文件里。返回渲染好的 HTML，前端直接插。
    """
    h = _load_session(_sid(request))["history"]
    if len(h) < 2:
        return {"turn": None}
    return {"turn": {"user": h[-2]["content"], "reply": render_markdown(h[-1]["content"])}}


@router.get("/api/resumes")
def list_all_resumes() -> dict:
    return {"resumes": ensure_all()}


@router.get("/api/resumes/{career_id}")
def get_resume(career_id: str) -> dict:
    saved = document(career_id)
    if not saved:
        raise HTTPException(status_code=404, detail=f"{career_id} 还没有简历")
    return saved


class PatchOp(BaseModel):
    op: Literal["set", "add", "remove", "move"]
    path: str = Field(description="JSON Pointer：列表段写下标、对象段写键名，如 /work_history/0/projects/1/description")
    value: Any = None
    to: int | None = Field(default=None, description="move 的目标下标")


class ResumeEditRequest(BaseModel):
    ops: list[PatchOp] = Field(default_factory=list, description="这一批要做的改动，空列表等于什么都不改")
    reason: str = Field(default="手动编辑", description="记进改动历史的一句话")


@router.post("/api/resumes/{career_id}/edits")
def patch_resume(career_id: str, body: ResumeEditRequest) -> dict:
    try:
        apply_edits(career_id, [op.model_dump() for op in body.ops], body.reason)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return document(career_id)


@router.post("/api/persona/init")
async def persona_init(file: UploadFile = File(...)) -> dict:
    try:
        text = await read_upload(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        persona = init_persona_from_text(text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 解析失败：{e}")
    return persona


@router.get("/api/persona")
def persona() -> dict:
    return get_persona()


@router.patch("/api/persona/targets")
def patch_targets(body: TargetRequest) -> dict:
    return save_targets(body.target, body.target_base, body.target_salary)

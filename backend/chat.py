"""Chat 领域：agent loop、工具注册表、会话、system prompt 拼装。

边界：本模块是**领域层**，HTTP 边界在 api_chat.py（Worker）——四个
chat 端点、body 解析、SSE 组装都在那边。FastAPI 路由层已于 2026-10-16
整体退役（main.py / routes_legacy.py 删除），领域代码离线与 Worker 通用。

session 存取走 sessions 模块（C2b 起落 R2，chat_sessions/{sid}.json）：
_load_session / _save_session 是它的薄包装，整个领域层只经这两句话。
"""

from __future__ import annotations

import json
import logging

from common import GEMINI_MODEL, render_markdown, call_llm_async, call_llm_stream_async
from sessions import load as _load_session, save as _save_session
from utils import load_file
from tools import (
    auto_compact, read_persona, read_careers,
    start_resume, read_resume, critique_resume, analyze_jd,
)
from resume import (
    DIRECTIVE,
    RESUME_DIR,
    body as resume_body,
    document,
    list_resumes,
)

logger = logging.getLogger("argus.chat")

SYSTEM_PROMPT = """你是 Argus，一个职业发展助手。

你的目标是充分了解用户，为他/她找到心仪合适的工作。
通过持续对话理解用户的画像和求职意向，帮他/她准备简历、分析岗位 JD、判断岗位匹配度、找出岗位适合投递的简历，提供打招呼开场白等求职策略。

你的材料都在只读文件里，需要哪份读哪份，不要预读、不要一次读全。
读哪个由当前问题决定：read_careers 读 careers.json，岗位侧要什么能力；
read_resume(career_id) 读 data/resumes 下他自己改过的那份简历。没有的别硬读。

读完直接回答用户关心的事，不要罗列你读了哪些文件、也不要复述文件里的原始结构。
每次只输出一两句话。不要长篇大论。

用户**贴来一份岗位 JD**时，调 analyze_jd 从现有简历里挑出最合适的，并把开场白一并给他。

**简历**：用户想为某个职能准备简历时（不管是他说「我想投经营分析」还是「帮我改改简历」），
你自己判断该针对哪个职能，调 start_resume 开始跟他聊——不要问用户要点哪个按钮。
简历**由用户自己在 Resume 页亲手改**，你不要替他写，也不要问要不要帮他写。"""


async def _current_resume(sid: str) -> dict | None:
    sess = await _load_session(sid)
    rc = sess.get("resume_career")
    return load_file(RESUME_DIR / f"{rc}.json") if rc else None


async def _system_prompt(sid: str) -> str:
    saved = await _current_resume(sid)
    turns = [SYSTEM_PROMPT]
    resumes = list_resumes()
    if resumes:
        lines = "\n".join(f"- {r['career_id']}｜{r['career_name']}｜改于 {r['updated_at']}" for r in resumes)
        turns.append(f"## 他现有的简历（data/resumes）\n\n{lines}")
    if saved:
        stamp = f"最后由用户自己修改于 {saved.get('updated_at', '未知时间')}"
        turns.append(DIRECTIVE.format(career=saved["career_name"]))
        turns.append(
            f"## 当前简历（{saved['career_name']}，{stamp}）\n\n{resume_body(saved)}\n\n"
            "上面是磁盘上的当前版本，**他随时可能刚在 Resume 页改过**。你在这段对话里读到的、"
            "自己记下的任何简历内容一律作废，以这一份为准。")
    return "\n\n".join(turns)


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
            "name": "analyze_jd",
            "description": "用户贴来一份岗位 JD 时调它：从 data/resumes 现有简历里挑出最合适的一份，并给出一段招聘平台上打招呼的开场白。JD 原文从用户消息里取，原样传入，不要自己编。",
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
    "analyze_jd": analyze_jd,
}

RESUME_TOOLS = {
    "start_resume": start_resume,
    "read_resume": read_resume,
    "critique_resume": critique_resume,
}

MAX_TOOL_STEPS = 4


def _tc(tool_call, name: str):
    """tool_call 字段读取，兼容对象（离线 SDK）与 dict（Worker fetch）两种形状。"""
    if isinstance(tool_call, dict):
        return tool_call.get(name)
    return getattr(tool_call, name, None)


def _tc_fn(tool_call, name: str):
    fn = _tc(tool_call, "function")
    if fn is None:
        return None
    return fn.get(name) if isinstance(fn, dict) else getattr(fn, name, None)


def _awaitable(v) -> bool:
    return hasattr(v, "__await__") or hasattr(v, "send")


async def _execute_tool(sid: str, name: str, args: dict) -> tuple[dict, list[dict] | None]:
    """工具分发。reader 有同步有异步（LLM 调用那几个）——awaitable 才 await。"""
    fn = READERS.get(name) or RESUME_TOOLS.get(name)
    if fn is None:
        return {"status": "error", "detail": f"没有 {name} 这个工具"}, None
    result = fn(**args)
    if _awaitable(result):
        result = await result
    if name == "start_resume" and result.get("status") == "ok":
        sess = await _load_session(sid)
        sess["resume_career"] = args["career_id"]
        await _save_session(sid, sess)
    return result, None


async def answer(sid: str, message: str, on_delta=None) -> dict:
    """一轮对话：agent loop（≤4 步工具）→ 落会话 → 拼响应。

    on_delta 非空走流式传输。与原 chat.py::chat_stream 的口径一致：**先落会话
    再拼响应**——响应丢了（客户端取消、断流）也还能从 history 捞回来。
    """
    cards = None
    messages = await _messages(sid, message)
    msg = None
    # max_tokens=4096：SYSTEM_PROMPT 要求简短，但 1024 实测会把正常回答切断
    # （用户线上撞到过）。ramble 风险靠 pinned + sticky 控制，不靠饿着模型。
    # pinned/sticky：工具轮钉模型。第一轮钉 gemini；**之后钉上一轮真正接话的
    # 那个模型**——gemini 的 thought_signature 只认自己产出的 tool_calls，
    # 中途换模型必 400（groq 接了一轮再换回 gemini 实测复现）。
    # pinned 只挪第一次尝试，挂了照常降级。
    pin = GEMINI_MODEL
    for _ in range(MAX_TOOL_STEPS):
        if on_delta is not None:
            msg = await call_llm_stream_async(messages, on_delta, tools=TOOLS, max_tokens=4096, pinned=pin)
        else:
            msg = await call_llm_async(messages, tools=TOOLS, max_tokens=4096, pinned=pin)
        if not msg["tool_calls"]:
            return await _finish(sid, message, msg, cards)
        pin = msg["model"]
        # tool_calls 回带要原样：Gemini 3 要求多轮函数调用带回首轮的
        # thought_signature（extra_content 里），重建三件套会丢，下一步直接 400。
        # SDK 对象走 model_dump（与从前一致）；fetch 的 dict 原样拷贝。
        messages.append({"role": "assistant", "content": msg["content"],
                         "tool_calls": [t if isinstance(t, dict) else t.model_dump(exclude_none=True)
                                        for t in msg["tool_calls"]]})
        for t in msg["tool_calls"]:
            result, found = await _execute_tool(sid, _tc_fn(t, "name"),
                                                json.loads(_tc_fn(t, "arguments") or "{}"))
            cards = found or cards
            messages.append({"role": "tool", "tool_call_id": _tc(t, "id"),
                             "content": json.dumps(result, ensure_ascii=False)})
    return await _finish(sid, message, msg, cards)


async def _messages(sid: str, message: str) -> list[dict]:
    """一轮对话要发给模型的消息。流式和非流式共用。"""
    sess = await _load_session(sid)
    return [
        {"role": "system", "content": await _system_prompt(sid)},
        *await auto_compact(sess["history"]),
        {"role": "user", "content": message},
    ]


async def _finish(sid: str, message: str, msg: dict, cards: list | None) -> dict:
    """把这一轮落进会话并拼出响应。落盘在拼响应之前，响应丢了也还能捞回来。"""
    sess = await _load_session(sid)
    reply = msg["content"] or ""
    sess["history"].append({"role": "user", "content": message})
    sess["history"].append({"role": "assistant", "content": reply})
    await _save_session(sid, sess)
    resp = {"reply": render_markdown(reply), "model": msg["model"]}
    if cards:
        resp["jobs"] = cards
    card = await _resume_card(sid)
    if card:
        resp["resume"] = card
    return resp


async def clear(sid: str) -> dict:
    sess = await _load_session(sid)
    n = len(sess["history"])
    sess["history"].clear()
    mode = sess["resume_career"]
    sess["resume_career"] = None
    await _save_session(sid, sess)
    return {"cleared": n, "resume_career": mode}


async def history(sid: str) -> dict:
    """最后一轮对话，用来在请求被掐断后把已经算完的答案取回来。

    请求失败不代表这一轮没跑完——切走 App、运营商断流都是客户端单方面取消，
    后端照跑完并存了盘（_save_session 在拼响应之前）。此时界面只能显示一句
    Load failed，答案却躺在会话里。返回渲染好的 HTML，前端直接插。
    """
    h = (await _load_session(sid))["history"]
    if len(h) < 2:
        return {"turn": None}
    return {"turn": {"user": h[-2]["content"], "reply": render_markdown(h[-1]["content"])}}


async def _resume_card(sid: str) -> dict | None:
    saved = await _current_resume(sid)
    return document((await _load_session(sid))["resume_career"]) if saved else None

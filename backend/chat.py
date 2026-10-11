"""Chat 领域：对话循环与工具注册 + 简历上传初始化 Persona。

本文件是 chat 领域的注册中心：SYSTEM_PROMPT、TOOLS / READERS 注册表、
agent loop、以及全部路由。被 LLM tool call 调用的函数实现在 tools.py——
注册归这里，实现归那里。

上传与解析实现全在 persona，本文件只做路由薄层。历史存内存单例，重启即丢。
"""

import json
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from common import render_markdown, call_llm
from tools import auto_compact, read_persona, read_careers, read_gaps_index, read_gap, search_jobs
from persona import get_persona, init_persona_from_text, read_upload, save_targets

logger = logging.getLogger("argus.chat")

router = APIRouter()

SYSTEM_PROMPT = """你是 Argus，一个职业发展助手。

你的目标是充分了解用户，为他/她找到心仪合适的工作。
通过持续对话理解用户经历，用户求职的目标，期望薪资范围，以及期望工作城市。

你对用户的了解全部存在四个只读文件里，需要时自己判断读哪个，不要预读、也不要一次读全：
read_persona（用户是谁、做过什么、想去哪）、read_careers（岗位侧要什么能力）、
read_job_gaps（哪些岗位已有差距解读）、read_job_gap（某个岗位差在哪）。
先用 read_persona 确认用户底细，再用 read_careers 看岗位要求，最后才用 read_job_gap 核对具体岗位。

读完直接回答用户关心的事，不要罗列你读了哪些文件、也不要复述文件里的原始结构。
每次只输出一两句话。不要长篇大论。"""


_history: list[dict] = []


class ChatRequest(BaseModel):
    message: str


# 以前的旧 tag 解析逻辑已删除，保留 Targets 定义供 Patch 接口使用
class TargetRequest(BaseModel):
    target: list[str] = Field(default_factory=list)
    target_base: str = ""
    target_salary: str = ""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_persona",
            "description": "读用户的简历与求职意向：工作经历、项目、技能，以及意向职位/城市/薪资。凡是问到用户是谁、做过什么、能投哪，先读这个。",
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
]


# update_persona / search_boss_jobs 暂时停用：TOOLS 里没注册，下面两段代码留着，
# 想开回来把它们加回 TOOLS 即可。
READERS = {
    "read_persona": read_persona,
    "read_careers": read_careers,
    "read_job_gaps": read_gaps_index,
    "read_job_gap": read_gap,
}


MAX_TOOL_STEPS = 4


def _execute_tool(name: str, args: dict) -> tuple[dict, list[dict] | None]:
    """执行工具，返回 (回喂 LLM 的 JSON 结果, 本轮岗位卡片或 None)。"""
    if name in READERS:
        return READERS[name](**args), None
    if name == "update_persona":
        save_targets(args["target"], args["target_base"], args["target_salary"])
        return {"status": "ok"}, None
    return search_jobs(args["keyword"])


def _run_agent(messages: list[dict]) -> tuple[dict, list[dict] | None]:
    """LLM ↔ 工具循环直到产出最终文本。卡片只旁路给前端，不进 LLM 上下文。"""
    cards = None
    for _ in range(MAX_TOOL_STEPS):
        msg = call_llm(messages, tools=TOOLS)
        if not msg["tool_calls"]:
            return msg, cards
        messages.append({
            "role": "assistant",
            "content": msg["content"],
            # 原样回填：Gemini 的 tool_call 携带 extra_content.google.thought_signature，丢了会 400
            "tool_calls": [t.model_dump(exclude_none=True) for t in msg["tool_calls"]],
        })
        for t in msg["tool_calls"]:
            result, found = _execute_tool(t.function.name, json.loads(t.function.arguments))
            cards = found or cards
            messages.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps(result, ensure_ascii=False)})
    return msg, cards


@router.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    """单轮问答 + Agent 工具循环。历史存本进程内存，重启即丢。"""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息为空")

    try:
        msg, cards = _run_agent([
            {"role": "system", "content": SYSTEM_PROMPT},
            *auto_compact(_history),
            {"role": "user", "content": message},
        ])
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    reply = msg["content"] or ""
    _history.append({"role": "user", "content": message})
    _history.append({"role": "assistant", "content": reply})
    resp = {"reply": render_markdown(reply)}
    if cards:
        resp["jobs"] = cards
    return resp


@router.post("/api/chat/clear")
def chat_clear() -> dict:
    """清空对话历史。摘要与原文都只在本进程内存里，重启同样会丢，
    给用户一个「说错了，重来」的动作即可，不必追问确认。"""
    n = len(_history)
    _history.clear()
    return {"cleared": n}


@router.post("/api/persona/init")
async def persona_init(file: UploadFile = File(...)) -> dict:
    """上传 md/txt 简历，调 LLM 解析出 Persona 并落盘。失败 502，不降级。"""
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
    """只写求职意向三个字段，简历抽取结果保留。前端解析 Argus 的 <target> 后调用。"""
    return save_targets(body.target, body.target_base, body.target_salary)
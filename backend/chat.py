"""Chat 领域：对话 + 简历上传初始化 Persona。

上传与解析实现全在 persona，本文件只做路由薄层。
对话调智谱，system prompt 里拼上已解析的 persona，历史存内存单例。
"""

import json
import logging
import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from common import MODEL_CHAIN, render_markdown, call_llm
from persona import get_persona, init_persona_from_text, read_upload, save_targets
from crawler import fetch_boss_html, parse_jobs

logger = logging.getLogger("argus.chat")

router = APIRouter()

SYSTEM_PROMPT = """你是 Argus，一个职业发展助手。

你的目标是充分了解用户，为他/她找到心仪合适的工作。
通过持续对话理解用户经历，用户求职的目标，期望薪资范围，以及期望工作城市。
用户的简历信息如果存在，已经放在下方 JSON 里。

每次只输出一两句话。不要长篇大论。

当用户明确了求职意向（包括职位列表、意向城市、期望薪资），你必须调用 update_persona 工具将其保存。
- target 是职位列表，按意向度从高到低排列。
- 三项都明确后才能调用。

当用户要求在 Boss 直聘上搜索岗位时，使用 search_boss_jobs 工具。
- 例如：“帮我搜一下上海的数据分析岗位” -> 调用 search_boss_jobs(keyword="上海 数据分析")。"""

_history: list[dict] = []

MAX_HISTORY = 20


class ChatRequest(BaseModel):
    message: str


# 以前的旧 tag 解析逻辑已删除，保留 Targets 定义供 Patch 接口使用
class TargetRequest(BaseModel):
    target: list[str] = Field(default_factory=list)
    target_base: str = ""
    target_salary: str = ""


def _system_with_persona() -> str:
    data = get_persona()
    if not data:
        return SYSTEM_PROMPT
    dumped = json.dumps(data, ensure_ascii=False, indent=2)
    return f"{SYSTEM_PROMPT}\n\n用户的简历信息：\n{dumped}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_persona",
            "description": "记录用户的求职意向。只在用户明确告知时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "array", "items": {"type": "string"}, "description": "职位列表，按意向度从高到低"},
                    "target_base": {"type": "string", "description": "意向城市"},
                    "target_salary": {"type": "string", "description": "期望薪资区间"},
                },
                "required": ["target", "target_base", "target_salary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_boss_jobs",
            "description": "根据用户的职位需求在 Boss 直聘上搜索岗位并解析返回。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，例如 数据分析"},
                },
                "required": ["keyword"],
            },
        },
    }
]


@router.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    """单轮问答。历史存在本进程内存里，重启即丢。支持 tool calling 更新意向，Gemini 失败自动切智谱。"""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息为空")
    _history.append({"role": "user", "content": message})

    # 容灾链：统一走 call_llm
    try:
        msg = call_llm(
            messages=[
                {"role": "system", "content": _system_with_persona()},
                *_history[-(MAX_HISTORY - 1):],
            ],
            tools=TOOLS,
            temperature=0.7,
        )
    except RuntimeError as e:
        _history.pop()
        raise HTTPException(status_code=502, detail=str(e))

    # 处理 Tool Call
    if msg.tool_calls:
        tool = msg.tool_calls[0]
        args = json.loads(tool.function.arguments)
        
        if tool.function.name == "update_persona":
            save_targets(args["target"], args["target_base"], args["target_salary"])
            return {"reply": "好的，已记录你的求职意向。"}
            
        elif tool.function.name == "search_boss_jobs":
            try:
                html = fetch_boss_html(args["keyword"])
                jobs = parse_jobs(html)
                formatted = "\n".join([f"- **{j.get('title')}** | {j.get('company')} | {j.get('salary')}" for j in jobs[:5]])
                return {"reply": f"为您找到以下岗位：\n{formatted}"}
            except Exception as e:
                return {"reply": f"获取岗位失败：{e}"}

    reply = msg.content or ""
    _history.append({"role": "assistant", "content": reply})
    return {"reply": render_markdown(reply)}


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
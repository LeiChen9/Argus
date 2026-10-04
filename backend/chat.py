"""Chat 领域：对话 + 简历上传初始化 Persona。

上传与解析实现全在 persona，本文件只做路由薄层。
对话调智谱，system prompt 里拼上已解析的 persona，历史存内存单例。
"""

import json
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from common import GEMINI_MODEL, llm_client, render_markdown
from persona import get_persona, init_persona_from_text, read_upload

logger = logging.getLogger("argus.chat")

router = APIRouter()

SYSTEM_PROMPT = """你是 Argus，一个职业发展助手。

你的目标是充分了解用户，为他/她找到心仪合适的工作。
通过持续对话理解用户经历，用户求职的目标，期望薪资范围，以及期望工作城市。
用户的简历信息如果存在，已经放在下方 JSON 里。

每次只输出一两句话。不要长篇大论。"""

_history: list[dict] = []

MAX_HISTORY = 20


class ChatRequest(BaseModel):
    message: str


def _system_with_persona() -> str:
    data = get_persona()
    if not data:
        return SYSTEM_PROMPT
    dumped = json.dumps(data, ensure_ascii=False, indent=2)
    return f"{SYSTEM_PROMPT}\n\n用户的简历信息：\n{dumped}"


@router.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    """单轮问答。历史存在本进程内存里，重启即丢。失败 502，不降级。"""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息为空")
    _history.append({"role": "user", "content": message})
    try:
        resp = llm_client().chat.completions.create(
            model=GEMINI_MODEL,
            messages=[
                {"role": "system", "content": _system_with_persona()},
                *_history[-(MAX_HISTORY - 1):],
            ],
            temperature=0.7,
        )
    except Exception as e:
        _history.pop()
        raise HTTPException(status_code=502, detail=f"对话失败：{e}")
    reply = resp.choices[0].message.content or ""
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
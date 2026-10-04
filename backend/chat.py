"""Chat 领域：对话 + 简历上传初始化 Persona。

上传与解析实现全在 persona，本文件只做路由薄层。
"""

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from persona import get_persona, init_persona_from_text, read_upload

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    return {"reply": f"收到：{body.message}"}


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
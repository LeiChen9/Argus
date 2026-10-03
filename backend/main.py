from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from persona_model import Persona

app = FastAPI(title="Argus")


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    return {"reply": f"收到：{body.message}"}


@app.get("/api/persona")
def persona() -> dict:
    return Persona().model_dump(mode="json")


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
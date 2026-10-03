from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Argus")

PERSONA_MOCK = {
    "experience": [],
    "skills": [],
    "knowledge": [],
    "projects": [],
    "domain_expertise": [],
    "communication": [],
    "career_preferences": [],
    "strengths": [],
    "weaknesses": [],
    "evidence": [],
    "goals": [],
}


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    return {"reply": f"收到：{body.message}"}


@app.get("/api/persona")
def persona() -> dict:
    return PERSONA_MOCK


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
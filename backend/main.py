import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import chat
import jobs
import me

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Argus")

app.include_router(chat.router)
app.include_router(jobs.router)
app.include_router(me.router)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
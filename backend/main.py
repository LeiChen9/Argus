import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

import chat
import jobs
import me

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Argus")


@app.middleware("http")
async def no_stale_static(request: Request, call_next):
    """静态资源一律不缓存。

    不设 Cache-Control 时浏览器会用 Last-Modified 做启发式缓存：文件刚改过
    （Last-Modified 是几分钟前）就仍然算"新鲜"，于是继续跑旧 JS。PWA 模式下
    iOS Safari 判得更松，改了前端也不生效，只能强刷。开发机自用，牺牲缓存
    换"改完刷新就是新的"。
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(chat.router)
app.include_router(jobs.router)
app.include_router(me.router)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
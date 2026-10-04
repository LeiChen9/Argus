"""底层工具：只放 IO 与.env 读取，不含任何业务。

- read_env_key: 从项目根 .env 读 key
- llm_client: 走 Gemini 的 OpenAI 兼容端点，chat 和 persona 共用
- load_json_file / save_json_file: persona.json 落盘底层
- clean_llm_json: 去 markdown 代码块后解析 JSON
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from markdown_it import MarkdownIt
from openai import OpenAI

GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

_MD = MarkdownIt("commonmark", {"html": False, "linkify": True})
_MD.enable("strikethrough")


def project_root() -> Path:
    """backend/ 的父目录，即项目根（.env 所在）。"""
    return Path(__file__).resolve().parents[1]


def read_env_key(name: str) -> str:
    """从项目根 .env 读 key。key 不入库（.env 已 gitignore）。"""
    for line in (project_root() / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip("'").strip('"')
    raise RuntimeError(f".env 缺少 {name}")


@cache
def llm_client() -> OpenAI:
    """Gemini 的 OpenAI 兼容端点。不装 google-genai，SDK 复用已有的 openai。"""
    return OpenAI(
        api_key=read_env_key("gemini_apiKey"),
        base_url=GEMINI_BASE_URL,
    )


def load_json_file(path: Path) -> dict:
    """读 JSON 文件。不存在抛 FileNotFoundError，由调用方决定回退。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_file(path: Path, payload: str) -> None:
    """写文本到文件。调用方负责序列化，本函数只做 IO。"""
    path.write_text(payload + "\n", encoding="utf-8")


def render_markdown(text: str) -> str:
    """LLM 回复里的 markdown 转 HTML，供前端气泡直接插。

    html=False：裸 <script>/<b> 一律转义成文本。LLM 会照抄简历里的文字，
    简历里若带标签不能变成可执行 HTML。链接仍走 markdown-it 的 URL 校验。
    """
    return _MD.render(text)


def clean_llm_json(raw: str) -> dict:
    """去 markdown 代码块后解析 JSON。LLM 偶发包 ```json 块。"""
    body = raw.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if body.startswith("json"):
            body = body[4:].strip()
    return json.loads(body)

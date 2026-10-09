"""底层工具：只放 IO 与.env 读取，不含任何业务。

- read_env_key: 从项目根 .env 读 key
- llm_client: 走 Gemini 的 OpenAI 兼容端点，chat 和 persona 共用
- active_chain / call_llm: 模型容灾链，按 active_chain 顺序故障转移
- load_json_file / save_json_file: persona.json 落盘底层
- clean_llm_json: 去 markdown 代码块后解析 JSON
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from pathlib import Path

from chinese_calendar import is_holiday, is_workday
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


SCRAPER_API_KEY = read_env_key("scraper_apiKey")


@cache
def llm_client() -> OpenAI:
    """Gemini 的 OpenAI 兼容端点。"""
    return OpenAI(
        api_key=read_env_key("gemini_apiKey"),
        base_url=GEMINI_BASE_URL,
    )


@cache
def zhipu_client() -> OpenAI:
    """智谱备用端点。"""
    return OpenAI(
        api_key=read_env_key("zhipu_realtime_apiKey"),
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )


@cache
def deepseek_client() -> OpenAI:
    """DeepSeek 兜底端点。非开放时段见 deepseek_open。"""
    return OpenAI(
        api_key=read_env_key("deepseek_apiKey"),
        base_url="https://api.deepseek.com/v1/",
    )


# ── DeepSeek 开放时段 ──────────────────────────────────────────────────────
# DeepSeek 不是 7×24 可用：北京时间周一至周五（法定节假日除外）9:00-12:00、
# 14:00-18:00 为高峰，峰段调用会被限流。先判时段再入链，而不是失败后重试。
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_PEAK_HOURS = frozenset(range(9, 12)) | frozenset(range(14, 18))


def deepseek_open(now: datetime | None = None) -> bool:
    """DeepSeek 现在开放吗：法定节假日全天，否则工作日的非峰段小时。

    节假日认 chinese_calendar：调休补班的周六算工作日，法定假期的周日算
    节假日，手写 weekday() 判断两者都会判错。
    """
    now = now or datetime.now()
    if is_holiday(now.date()):
        return True
    return is_workday(now.date()) and now.hour not in DEEPSEEK_PEAK_HOURS


# 模型链：按优先级排序。DeepSeek 缺 key 或不在开放时段内不入链。
MODEL_CHAIN = [
    {"name": GEMINI_MODEL, "client": llm_client},
    {"name": "glm-4.7-flash", "client": zhipu_client},
    {"name": DEEPSEEK_MODEL, "client": deepseek_client},
]


def active_chain() -> list[dict]:
    """当下真正可用的模型链。"""
    try:
        read_env_key("deepseek_apiKey")
        deepseek_usable = deepseek_open()
    except RuntimeError:
        deepseek_usable = False
    return [
        item
        for item in MODEL_CHAIN
        if item["name"] != DEEPSEEK_MODEL or deepseek_usable
    ]



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


def call_llm(messages: list[dict], *, tools: list[dict] | None = None, temperature: float = 0.7) -> dict:
    """统一 LLM 调用，按 active_chain 顺序故障转移。返回 message 内容与实际使用的模型名。"""
    import logging
    logger = logging.getLogger("argus.llm")
    last_err = None
    for item in active_chain():
        model_name = item["name"]
        client = item["client"]()
        try:
            kwargs = {"model": model_name, "messages": messages, "temperature": temperature}
            if tools:
                kwargs["tools"] = tools
            resp = client.chat.completions.create(**kwargs)
            logger.info(f"使用模型: {model_name}")
            msg = resp.choices[0].message
            return {"content": msg.content, "tool_calls": msg.tool_calls, "model": model_name}
        except Exception as e:
            last_err = e
            logger.warning(f"模型 {model_name} 失败: {e}")
    raise RuntimeError(f"所有模型均不可用: {last_err}")

"""Persona 领域：开发、评估和维护 Persona 相关内容。

- get_persona: Worker 每次直读 store，离线走内存单例
- save_persona/save_targets: async，Worker 落 R2（persona.json），离线落本地
- read_upload: 简历 md/txt 校验 + 读文本（限 200KB）。签名是 (name, bytes)，
  FastAPI 的 UploadFile 和 Worker 的 FormData File 都能喂
- parse_resume_llm: 调 Gemini 抽取（pinned），失败降级到链上其余模型
- init_persona_from_text: 从简历文本建 Persona 并落盘

没有数据模型。内部就是一个 dict，原样落 persona.json，字段约定只写在
RESUME_TO_PERSONA 这段 prompt 里——它就是唯一的 schema 来源。想清楚了再加。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from common import GEMINI_MODEL, call_llm_async, clean_llm_json
import os
from utils import load_file, save_file_async, store_active

# 离线管线服务于单个账号：产物落 data/<用户>/，与 R2 上的命名空间一致。
# 默认 lbb；给别的账号跑离线脚本就 ARGUS_USER=xxx python3 …（Worker 侧由 cookie 决定）。
USER = os.environ.get("ARGUS_USER", "lbb")

logger = logging.getLogger("argus.persona")


RESUME_TO_PERSONA = """分析简历，抽取结构化信息。只输出 JSON，不要解释，不要 markdown 代码块。

抽取规则：
1. work_history：按时间倒序，最近的一段放最前。每段给出公司全称、职位、起止日期、该职位的整体职责，以及这段任职真正承载方法与成效的项目。
2. projects：name 是项目名，description 是具体的项目内容描述。
3. skills：在候选人职位与行业语境下提炼 6-12 项专业能力，根据候选人经历进行总结归纳。
4. education：学校、学历、专业、起止日期。
5. 日期一律 YYYY-MM。缺失、推断不出、或仍在职的，一律填空字符串 ""，不要写 null，也不要写「至今」。

格式：
{{
  "work_history": [
    {{
      "company": "公司全称",
      "role": "职位",
      "start_date": "2023-05",
      "end_date": "2025-07",
      "projects": [
        {{"name": "项目名", "description": "做法与成效"}}
      ]
    }}
  ],
  "skills": ["能力名"],
  "education": [
    {{
      "university": "学校",
      "degree": "学历",
      "major": "专业",
      "start_date": "2012-09",
      "end_date": "2016-06"
    }}
  ]
}}

简历：
{resume}
"""


def build_resume_prompt(resume_text: str) -> str:
    return RESUME_TO_PERSONA.format(resume=resume_text)

STORE_PATH = Path(__file__).resolve().parents[1] / "data" / USER / "persona.json"

MAX_BYTES = 200 * 1024
ALLOWED_SUFFIX = {".md", ".txt"}

# 聊天里聊出来的求职意向，不是简历抽取的产物，故不进 RESUME_TO_PERSONA。
TARGET_KEYS = ("target", "target_base", "target_salary")

_persona: dict | None = None


def get_persona() -> dict:
    """内存单例，没有就从 persona.json 恢复，再没有就返回空 dict。

    Worker 模式不走单例：isolate 会被后续请求复用，单例会让刚上传/改过的
    persona 在这批请求里继续吐旧值。store 非空即 Worker 模式，每次直读。
    """
    global _persona
    if store_active():
        return load_file(STORE_PATH) or {}
    if _persona is not None:
        return _persona
    if STORE_PATH.exists():
        _persona = load_file(STORE_PATH)
        return _persona
    _persona = {}
    return _persona


async def save_targets(
    target: list[str],
    target_base: str,
    target_salary: str,
) -> dict:
    """只更新求职意向三个字段，其余键（简历抽取结果）原样保留。

    单独开这个口而不是复用 save_persona：上传简历是整体覆盖，
    若聊天里聊出的意向被一并抹掉，用户刚告诉我们的信息就白给了。
    """
    data = dict(get_persona())
    data["target"] = target
    data["target_base"] = target_base
    data["target_salary"] = target_salary
    return await save_persona(data)


async def save_persona(data: dict) -> dict:
    """落盘并返回存入的数据。Worker 落 R2，离线落本地 + 内存单例。"""
    global _persona
    _persona = data
    await save_file_async(STORE_PATH, data)
    return data


def read_upload(name: str, raw: bytes) -> str:
    """校验后缀并读文本。只收 .md / .txt，超 200KB 拒收。

    签名收 (文件名, 字节)：FastAPI 侧 UploadFile 拆开喂，Worker 侧 FormData
    的 File.text() 转 bytes 喂——两边的读取机制不同，校验逻辑只有一份。
    """
    suffix = Path(name or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise ValueError(f"只收 md/txt，收到 {suffix or '无后缀'}")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"文件过大（{len(raw)}B），上限 {MAX_BYTES}B")
    return raw.decode("utf-8", errors="replace")


async def parse_resume_llm(text: str) -> dict:
    """调 Gemini 抽取。pinned 钉链首；失败降级到链上其余模型（比从前的直接
    502 稳——抽取是结构化 JSON，弱模型还有 clean_llm_json 兜底修复）。"""
    logger.info("parse_resume_llm: start, resume_len=%d", len(text))
    body = text.strip()
    if not body:
        logger.info("parse_resume_llm: empty resume, return {}")
        return {}
    t0 = time.perf_counter()
    msg = await call_llm_async(
        [{"role": "user", "content": build_resume_prompt(body)}],
        temperature=0.1,
        pinned=GEMINI_MODEL,
        # 4096 够装一份完整履历的结构化 JSON；不收 8192——弱模型会 rampble。
        max_tokens=4096,
    )
    data = clean_llm_json(msg["content"])
    logger.info(
        "parse_resume_llm: success keys=%s model=%s latency_ms=%.0f",
        sorted(data), msg["model"], (time.perf_counter() - t0) * 1000,
    )
    return data


async def init_persona_from_text(text: str) -> dict:
    """从简历文本调 LLM 建 Persona 并落盘。失败抛错，由 HTTP 层转 502。

    聊出来的求职意向不丢：简历抽取只给简历里有的字段，
    target / target_base / target_salary 沿用已存的。
    """
    data = await parse_resume_llm(text)
    current = get_persona()
    for key in TARGET_KEYS:
        if key in current:
            data[key] = current[key]
    return await save_persona(data)

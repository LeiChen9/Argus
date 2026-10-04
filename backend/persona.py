"""Persona 领域：开发、评估和维护 Persona 相关内容。

- get/save_persona: 内存单例 + 落 persona.json（被 gitignore），B 片再迁 SQLite
- read_upload: 简历 md/txt 校验 + 读文本（限 200KB）
- parse_resume_llm: 调智谱抽取，失败抛错不降级
- init_persona_from_text: 从简历文本建 Persona 并落盘

没有数据模型。内部就是一个 dict，原样落 persona.json，字段约定只写在
RESUME_TO_PERSONA 这段 prompt 里——它就是唯一的 schema 来源。想清楚了再加。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import UploadFile
from openai import OpenAI

from common import clean_llm_json, load_json_file, read_env_key, save_json_file

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

STORE_PATH = Path(__file__).resolve().parent / "persona.json"

MAX_BYTES = 200 * 1024
ALLOWED_SUFFIX = {".md", ".txt"}

_persona: dict | None = None


def get_persona() -> dict:
    """内存单例，没有就从 persona.json 恢复，再没有就返回空 dict。"""
    global _persona
    if _persona is not None:
        return _persona
    if STORE_PATH.exists():
        _persona = load_json_file(STORE_PATH)
        return _persona
    _persona = {}
    return _persona


def save_persona(data: dict) -> dict:
    """更新内存单例并落盘。返回存入的数据本身，方便链式。"""
    global _persona
    _persona = data
    save_json_file(STORE_PATH, json.dumps(data, ensure_ascii=False, indent=2))
    return data


async def read_upload(file: UploadFile) -> str:
    """校验后缀并读文本。只收 .md / .txt，超 200KB 拒收。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise ValueError(f"只收 md/txt，收到 {suffix or '无后缀'}")
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise ValueError(f"文件过大（{len(raw)}B），上限 {MAX_BYTES}B")
    return raw.decode("utf-8", errors="replace")


def parse_resume_llm(text: str) -> dict:
    """调智谱抽取。失败抛错（由 chat.py 转 502），不降级。返回 LLM 给的原样 JSON。"""
    logger.info("parse_resume_llm: start, resume_len=%d", len(text))
    body = text.strip()
    if not body:
        logger.info("parse_resume_llm: empty resume, return {}")
        return {}
    client = OpenAI(
        api_key=read_env_key("zhipu_realtime_apiKey"),
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model="glm-4.7-flash",
        messages=[{"role": "user", "content": build_resume_prompt(body)}],
        temperature=0.1,
    )
    data = clean_llm_json(resp.choices[0].message.content)

    latency_ms = (time.perf_counter() - t0) * 1000
    usage = resp.usage
    logger.info(
        "parse_resume_llm: success keys=%s tokens_in=%d tokens_out=%d total_tokens=%d latency_ms=%.0f",
        sorted(data),
        usage.prompt_tokens,
        usage.completion_tokens,
        usage.total_tokens,
        latency_ms,
    )
    return data


def init_persona_from_text(text: str) -> dict:
    """从简历文本调 LLM 建 Persona 并落盘。失败抛错，不降级。"""
    return save_persona(parse_resume_llm(text))

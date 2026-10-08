"""Chat 领域：对话 + 简历上传初始化 Persona。

上传与解析实现全在 persona，本文件只做路由薄层。
对话走 LLM 与工具循环（Agent loop），system prompt 里拼上已解析的 persona，历史存内存单例。
"""

import json
import logging
import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from common import MODEL_CHAIN, render_markdown, call_llm
from persona import get_persona, init_persona_from_text, read_upload, save_targets
from crawler import fetch_liepin_html, parse_jobs, fetch_boss_recommendations, fetch_boss_details
from jobs import normalize, save_snapshot

logger = logging.getLogger("argus.chat")

router = APIRouter()

SYSTEM_PROMPT = """你是 Argus，一个职业发展助手。

你的目标是充分了解用户，为他/她找到心仪合适的工作。
通过持续对话理解用户经历，用户求职的目标，期望薪资范围，以及期望工作城市。
用户的简历信息如果存在，已经放在下方 JSON 里。

每次只输出一两句话。不要长篇大论。

你有两个工具：

update_persona：记录求职意向。target 是职位列表，按意向度从高到低；
职位列表、意向城市、期望薪资三项都明确后才调用。

search_boss_jobs：搜索岗位，结果以卡片展示。
- 只在用户主动要求搜索或查看岗位时调用；刚保存完意向，先问用户要不要搜一轮。
- keyword 由你组合：用户这次给的条件优先，缺的部分从简历信息的 target 和 target_base 补齐。
- 先走 BOSS直聘登录账号的个性化推荐（约 15-30 秒），不可用时自动回退猎聘关键词搜索。
- 结果先存入 Jobs 页，再以卡片直接展示给用户，你无需复述岗位明细。
- 返回 JSON 摘要：status / source / count / preview（前 5 条）。用一两句点评岗位质量、与用户意向的匹配度，或给出下一步建议。preview 是给你点评用的，不要在回复里罗列岗位清单。
- status 为 error 时如实转告，并建议换个关键词。"""

_history: list[dict] = []

MAX_HISTORY = 20


class ChatRequest(BaseModel):
    message: str


# 以前的旧 tag 解析逻辑已删除，保留 Targets 定义供 Patch 接口使用
class TargetRequest(BaseModel):
    target: list[str] = Field(default_factory=list)
    target_base: str = ""
    target_salary: str = ""


def _system_with_persona() -> str:
    data = get_persona()
    if not data:
        return SYSTEM_PROMPT
    dumped = json.dumps(data, ensure_ascii=False, indent=2)
    return f"{SYSTEM_PROMPT}\n\n用户的简历信息：\n{dumped}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_persona",
            "description": "记录用户的求职意向。只在用户明确告知时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "array", "items": {"type": "string"}, "description": "职位列表，按意向度从高到低"},
                    "target_base": {"type": "string", "description": "意向城市"},
                    "target_salary": {"type": "string", "description": "期望薪资区间"},
                },
                "required": ["target", "target_base", "target_salary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_boss_jobs",
            "description": "按关键词搜索岗位：结果先持久化到 Jobs 页，再在对话中以卡片展示，返回 JSON 摘要供你点评。仅在用户主动要求搜索或查看岗位时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "检索词，组合自用户本次要求与求职意向（target + target_base），如「上海 数据分析」"},
                },
                "required": ["keyword"],
            },
        },
    }
]


MAX_TOOL_STEPS = 4


def _search_jobs(keyword: str) -> tuple[dict, list[dict] | None]:
    try:
        raws = fetch_boss_recommendations(max_batches=1, timeout=25)
        source = "boss_recommend"
    except OSError:
        raws, source = [], "liepin"
    if source == "boss_recommend" and raws:
        details = fetch_boss_details(raws)
        merged = []
        for j in raws:
            key = j.get("encrypt_job_id") or j.get("job_link") or j.get("title")
            d = details.get(key)
            if d:
                j = {**j, "jd": d.get("jd", ""), "skill_tags": d.get("skill_tags", []), "boss_active_status": d.get("boss_active_status", "")}
                if j["jd"]:
                    merged.append(j)
        cards = [normalize(j, source) for j in merged]
    else:
        cards = [normalize(j, source) for j in raws]
    if not cards:
        source = "liepin"
        cards = [normalize(j, source) for j in parse_jobs(fetch_liepin_html(keyword))]
    if not cards:
        return {"status": "error", "detail": "两个来源都没有结果"}, None
    save_snapshot(cards, keyword)
    summary = {
        "status": "ok",
        "source": source,
        "count": len(cards),
        "preview": [{k: c[k] for k in ("title", "company", "salary")} for c in cards[:5]],
    }
    return summary, cards


def _execute_tool(name: str, args: dict) -> tuple[dict, list[dict] | None]:
    """执行工具，返回 (回喂 LLM 的 JSON 结果, 本轮岗位卡片或 None)。"""
    if name == "update_persona":
        save_targets(args["target"], args["target_base"], args["target_salary"])
        return {"status": "ok"}, None
    return _search_jobs(args["keyword"])


def _run_agent(messages: list[dict]) -> tuple[dict, list[dict] | None]:
    """LLM ↔ 工具循环直到产出最终文本。卡片只旁路给前端，不进 LLM 上下文。"""
    cards = None
    for _ in range(MAX_TOOL_STEPS):
        msg = call_llm(messages, tools=TOOLS)
        if not msg["tool_calls"]:
            return msg, cards
        messages.append({
            "role": "assistant",
            "content": msg["content"],
            # 原样回填：Gemini 的 tool_call 携带 extra_content.google.thought_signature，丢了会 400
            "tool_calls": [t.model_dump(exclude_none=True) for t in msg["tool_calls"]],
        })
        for t in msg["tool_calls"]:
            result, found = _execute_tool(t.function.name, json.loads(t.function.arguments))
            cards = found or cards
            messages.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps(result, ensure_ascii=False)})
    return msg, cards


@router.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    """单轮问答 + Agent 工具循环。历史存本进程内存，重启即丢。"""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息为空")

    try:
        msg, cards = _run_agent([
            {"role": "system", "content": _system_with_persona()},
            *_history[-(MAX_HISTORY - 1):],
            {"role": "user", "content": message},
        ])
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    reply = msg["content"] or ""
    _history.append({"role": "user", "content": message})
    _history.append({"role": "assistant", "content": reply})
    resp = {"reply": render_markdown(reply)}
    if cards:
        resp["jobs"] = cards
    return resp


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


@router.patch("/api/persona/targets")
def patch_targets(body: TargetRequest) -> dict:
    """只写求职意向三个字段，简历抽取结果保留。前端解析 Argus 的 <target> 后调用。"""
    return save_targets(body.target, body.target_base, body.target_salary)
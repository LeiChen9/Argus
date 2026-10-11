"""Chat 领域：对话循环与工具注册 + 简历上传初始化 Persona。

本文件是 chat 领域的注册中心：SYSTEM_PROMPT、TOOLS / READERS 注册表、
agent loop、以及全部路由。被 LLM tool call 调用的函数实现在 tools.py——
注册归这里，实现归那里。

上传与解析实现全在 persona，本文件只做路由薄层。历史存内存单例，重启即丢。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from common import render_markdown, call_llm
from utils import load_file
from tools import (
    auto_compact, read_persona, read_careers, read_gaps_index, read_gap, search_jobs,
    start_resume, read_resume, critique_resume,
)
from persona import get_persona, init_persona_from_text, read_upload, save_targets
# load 而不是 read_resume：上面已经从 tools 引了一个同名的包装函数。
# resume.body 拼 system prompt 用；这里在路由里 body 是请求体，撞名了所以取个别名。
from resume import (
    DIRECTIVE,
    RESUME_DIR,
    apply_edits,
    body as resume_body,
    document,
    ensure_all,
)

logger = logging.getLogger("argus.chat")

router = APIRouter()

SYSTEM_PROMPT = """你是 Argus，一个职业发展助手。

你的目标是充分了解用户，为他/她找到心仪合适的工作。
通过持续对话理解用户经历，用户求职的目标，期望薪资范围，以及期望工作城市。

你对用户的了解全部存在四个只读文件里，需要时自己判断读哪个，不要预读、也不要一次读全：
read_persona（**他最初上传的那份**履历与求职意向）、read_careers（岗位侧要什么能力）、
read_job_gaps（哪些岗位已有差距解读）、read_job_gap（某个岗位差在哪）。
先用 read_persona 确认用户底细，再用 read_careers 看岗位要求，最后才用 read_job_gap 核对具体岗位。

读完直接回答用户关心的事，不要罗列你读了哪些文件、也不要复述文件里的原始结构。
每次只输出一两句话。不要长篇大论。

**简历**：用户想为某个职能准备简历时（不管是他说「我想投经营分析」还是「帮我改改简历」），
你自己判断该针对哪个职能，调 start_resume 开始跟他聊——不要问用户要点哪个按钮。
简历**由用户自己在 Resume 页亲手改**，你不要替他写，也不要问要不要帮他写。"""

# 切到准备简历模式时追加在 SYSTEM_PROMPT 之后的指令。内容在 resume.DIRECTIVE，
# 它管的是怎么跟人聊；简历长什么样是 resume.critique 自己 prompt 的事。


def _current_resume() -> dict | None:
    """当前 Career 在磁盘上的简历。进模式后每轮都重读——他随时可能在 Resume 页改完
    再回来接着聊。"""
    return load_file(RESUME_DIR / f"{_resume_career}.json") if _resume_career else None


def _system_prompt() -> str:
    """按当前模式拼 system prompt。没有模式时就是 SYSTEM_PROMPT 本身。

    简历正文进的是 **system prompt**，不是 history。auto_compact 压的是 history，
    压完摘要里那份简历就过期了——模型会拿着用户改之前的旧版本跟他讨论他刚改过的地方，
    这正是「精神错乱」。system prompt 每次请求现拼、现读磁盘，天然免疫压缩。
    """
    saved = _current_resume()
    if not saved:
        return SYSTEM_PROMPT
    stamp = f"最后由用户自己修改于 {saved.get('updated_at', '未知时间')}"
    return "\n\n".join([
        SYSTEM_PROMPT,
        DIRECTIVE.format(career=saved["career_name"]),
        f"## 当前简历（{saved['career_name']}，{stamp}）\n\n{resume_body(saved)}\n\n"
        "上面是磁盘上的当前版本，**他随时可能刚在 Resume 页改过**。你在这段对话里读到的、"
        "自己记下的任何简历内容一律作废，以这一份为准。",
    ])


_history: list[dict] = []
# 当前正在准备的 Career。没进过模式就是 None——由 agent 调 start_resume 决定，
# 不由任何按钮或接口决定。和 _history 一样是进程内状态，重启即丢。
_resume_career: str | None = None


class ChatRequest(BaseModel):
    message: str


# 以前的旧 tag 解析逻辑已删除，保留 Targets 定义供 Patch 接口使用
class TargetRequest(BaseModel):
    target: list[str] = Field(default_factory=list)
    target_base: str = ""
    target_salary: str = ""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_persona",
            "description": "读用户最初上传的那份履历与求职意向：工作经历、项目、技能，以及意向职位/城市/薪资。凡是问到用户是谁、做过什么、能投哪，先读这个。注意这不是他在 Resume 页改过的当前版本，两份会分叉。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_careers",
            "description": "读岗位侧的 Career 定义：每个 Career 的定位、岗位归属判据、要求的能力清单（分 core/important/bonus）及成员岗位。用户问某类岗位要什么能力、或这几个岗位像不像一类时读。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_job_gaps",
            "description": "读岗位 × 用户差距解读的索引：公司、岗位、薪资、地点，约 30 条。只列清单不展开，先读它才知道有哪些岗位值得细看。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
{
        "type": "function",
        "function": {
            "name": "read_job_gap",
            "description": "读单个岗位的完整差距解读。job_id 取自 read_job_gaps 的索引。返回每条要求的匹配状态（transferable/gap）、缺什么、简历里哪一段作证据，以及当时的求职意向。用户关心某个具体岗位值不值得投时才读。",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "岗位 id，来自 read_job_gaps"}},
            "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_resume",
            "description": "开始为某个职能准备简历。这个职能还没有简历时，会按他自己传的那份履历（去掉求职意向）建一份底稿。返回该职能的定位与能力要求、以及他现有材料的提纲，够你据此开始提问。用户想投某个职能时调它，不要问用户要点哪个按钮。简历之后由他自己去 Resume 页改，你不碰它。",
            "parameters": {
                "type": "object",
                "properties": {"career_id": {"type": "string", "description": "career_id，来自 read_careers"}},
                "required": ["career_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_resume",
            "description": "读当前简历全文，也就是他在 Resume 页改过的那一份。只读——你没有任何修改它的工具。",
            "parameters": {
                "type": "object",
                "properties": {"career_id": {"type": "string", "description": "career_id"}},
                "required": ["career_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "critique_resume",
            "description": "筛简历。以招聘方视角判断这份简历够不够吸引他、会不会进面试。返回可改的地方（fixable，带 path）和只能继续挖的缺口（needs_mining）。结论和建议要讲给他听，由他自己去改——你只评，不写。",
            "parameters": {
                "type": "object",
                "properties": {"career_id": {"type": "string", "description": "career_id"}},
                "required": ["career_id"],
            },
        },
    },
]


# update_persona / search_boss_jobs 暂时停用：TOOLS 里没注册，下面两段代码留着，
# 想开回来把它们加回 TOOLS 即可。
READERS = {
    "read_persona": read_persona,
    "read_careers": read_careers,
    "read_job_gaps": read_gaps_index,
    "read_job_gap": read_gap,
}

# start_resume 会切模式，所以它不能走 READERS 的纯函数分派：它要改全局 _resume_career。
# 简历这一组已注册的工具都只碰 resumes/ 下的派生物（critique 写报告），不动事实源；
# 唯一的写动作是 start_resume 建底稿，同样只是拷 persona 的副本。
RESUME_TOOLS = {
    "start_resume": start_resume,
    "read_resume": read_resume,
    "critique_resume": critique_resume,
}


MAX_TOOL_STEPS = 4


def _execute_tool(name: str, args: dict) -> tuple[dict, list[dict] | None]:
    """执行工具，返回 (回喂 LLM 的 JSON 结果, 本轮岗位卡片或 None)。"""
    global _resume_career
    if name in READERS:
        return READERS[name](**args), None
    if name in RESUME_TOOLS:
        result = RESUME_TOOLS[name](**args)
        if name == "start_resume" and result.get("status") == "ok":
            _resume_career = args["career_id"]
        return result, None
    if name == "update_persona":
        save_targets(args["target"], args["target_base"], args["target_salary"])
        return {"status": "ok"}, None
    if name == "search_jobs":
        return search_jobs(args["keyword"])
    # 未知工具名不猜。漏到这里的名字若直接喂给 search_jobs，就是拿幻觉出来的参数去
    # 爬 boss 并覆盖 boss_jobs.json——那是无备份的事实源。回报给模型让它自己改对。
    return {"status": "error", "detail": f"没有 {name} 这个工具"}, None


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
            {"role": "system", "content": _system_prompt()},
            *auto_compact(_history),
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
    card = _resume_card()
    if card:
        resp["resume"] = card
    return resp


def _resume_card() -> dict | None:
    """当前模式下的简历正文 + 筛选报告，给 Chat 里的卡片渲染。

    不走工具旁路（不像 search_jobs 那样把结果夹带出来）：简历是落盘的事实，读回来
    比在工具返回里转一圈可靠，压缩历史后也还在。工具返回里只给摘要。

    正文全文也进了 system prompt（见 _system_prompt），这里给的是**给人看的**那份：
    他刚聊完，得能在对话里直接看到自己那份简历长什么样。
    """
    saved = _current_resume()
    return document(_resume_career) if saved else None


@router.post("/api/chat/clear")
def chat_clear() -> dict:
    """清空对话历史。摘要与原文都只在本进程内存里，重启同样会丢，
    给用户一个「说错了，重来」的动作即可，不必追问确认。

    同时退出简历模式：清空是「从头来」的意思，把上一段对话挖到一半的状态留着
    会让模型对着空上下文继续追问。已写出的简历在 data/resumes/ 里，不受影响。
    """
    global _resume_career
    n = len(_history)
    _history.clear()
    mode = _resume_career
    _resume_career = None
    return {"cleared": n, "resume_career": mode}


@router.get("/api/resumes")
def list_all_resumes() -> dict:
    """简历索引：Resume 页列表与 Career 页软链共用。

    走 ensure_all 而不是直接 list_resumes：每个 Career 都该有一份底稿，缺的那份在这
    里补上（逐字拷 persona，不调 LLM）。它在 GET 上写文件——写的是 resumes/ 下的派生物，
    不是事实源，且只在缺文件时才动手，重复调不会覆盖用户改过的内容。
    """
    return {"resumes": ensure_all()}


@router.get("/api/resumes/{career_id}")
def get_resume(career_id: str) -> dict:
    saved = document(career_id)
    if not saved:
        raise HTTPException(status_code=404, detail=f"{career_id} 还没有简历")
    return saved


class PatchOp(BaseModel):
    """一条改动。字段名跟 utils.apply_patch 吃的 ops 一模一样——用户手改和将来的
    自动 apply 共用一套 patch，不用维护两套方言。"""

    op: Literal["set", "add", "remove"]
    path: str = Field(description="JSON Pointer：列表段写下标、对象段写键名，如 /work_history/0/projects/1/description")
    value: Any = None


class ResumeEditRequest(BaseModel):
    ops: list[PatchOp] = Field(default_factory=list, description="这一批要做的改动，空列表等于什么都不改")
    reason: str = Field(default="手动编辑", description="记进改动历史的一句话")


@router.post("/api/resumes/{career_id}/edits")
def patch_resume(career_id: str, body: ResumeEditRequest) -> dict:
    """用户在 Resume 页亲手改简历。前端表单把变更的字段换算成 ops 发过来，这里照单落盘。

    这是 apply_edits 唯一的调用方——LLM 那三个写工具摘掉之后，AI 不再碰这个文件。
    apply_patch 的三条不变式原样成立：只动点名的条目、整份成败一起、edits 不许被 patch。

    失败分两种，状态码不同：path 写错是 400（带着是第几条 ops，前端能定位到哪个输入框），
    简历不存在是 404。两种都不写盘。
    """
    try:
        apply_edits(career_id, [op.model_dump() for op in body.ops], body.reason)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return document(career_id)


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
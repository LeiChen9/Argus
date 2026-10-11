"""Agent 工具的实现。注册表（TOOLS / READERS）在 chat.py。

划分依据是**这块代码归哪个领域、谁消费它**：被 LLM 当作 tool call 调用的
函数，实现全在这里——它们的服务对象是模型调用，不是某个 HTTP 路由。
chat.py 决定「有哪些工具、怎么注册」，tools.py 决定「工具被调用时干什么」。

- 四个只读工具：直接读 data/ 下的文件，不经 jobs.py 的路由函数
- search_jobs：搜岗位，唯一会写 data/ 的工具（落 boss_jobs.json 覆盖快照），
  暂时停用没注册，实现留着
- auto_compact：会话内存的 token 阈值压缩，由 /api/chat 在发请求前调，
  **不进 TOOLS**——压缩若是模型可选行为，模型不调就不压，阈值形同虚设

data/ 是事实源，工具只读不写。新增工具在此实现，再到 chat.py 注册。
"""

import json
import logging
from pathlib import Path

from common import call_llm, _input_tokens
from persona import get_persona
from jobs import gaps_by_job, normalize, save_snapshot, CAREERS, GAPS
from crawler import fetch_liepin_html, parse_jobs, fetch_boss_recommendations, fetch_boss_details

logger = logging.getLogger("argus.tools")


# ── 四个只读工具 ─────────────────────────────────────────────────────────


def read_persona() -> dict:
    """读简历与求职意向。没上传过时回 empty，让模型直接问用户要简历。"""
    data = get_persona()
    if not data:
        return {"status": "empty", "detail": "用户还没上传简历"}
    return {"status": "ok", "persona": data}


def read_careers() -> dict:
    """Career 全量：定位、归属判据、能力清单、成员岗位。6 个 Career 一次读完，
    模型才能横向比较。只回 careers 数组，generated_at 之类的元信息对回答没用。"""
    if not CAREERS.exists():
        return {"status": "error", "detail": "还没有 careers.json"}
    doc = json.loads(CAREERS.read_text(encoding="utf-8"))
    return {"status": "ok", "careers": doc.get("careers", [])}


def read_gaps_index() -> dict:
    """岗位 × persona 差距解读的索引。全量 438KB 读不动，先只给
    公司/岗位/薪资/地点，模型挑中哪个再用 job_id 读单条全文。"""
    if not GAPS.exists():
        return {"status": "error", "detail": "还没有 job_gaps.json"}
    doc = json.loads(GAPS.read_text(encoding="utf-8"))
    return {
        "status": "ok",
        "generated_at": doc.get("generated_at", ""),
        "jobs": [
            {
                "job_id": j["job"]["id"],
                "title": j["job"].get("title", ""),
                "company": j["job"].get("company", ""),
                "salary": j["job"].get("salary", ""),
                "location": j["job"].get("location", ""),
            }
            for j in doc.get("results", [])
        ],
    }


def read_gap(job_id: str) -> dict:
    """单个岗位的完整解读：每条要求与 persona 的匹配状态、缺什么、简历里的证据。
    带上跑分析时的求职意向快照——不然模型无从判断「对齐」是对齐到什么。"""
    row = gaps_by_job().get(job_id)
    if not row:
        return {"status": "error", "detail": f"没有 {job_id} 的解读"}
    return {"status": "ok", **row}


# search_boss_jobs 暂时停用：没注册进 chat.TOOLS，实现留着，想开回来把它加进
# TOOLS 即可。它是唯一会写 data/ 的工具（落 boss_jobs.json 覆盖快照）。
def search_jobs(keyword: str) -> tuple[dict, list[dict] | None]:
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


# ── 上下文压缩 ───────────────────────────────────────────────────────────

# 上下文按 token 阈值压缩，不再按轮数截断。128k = 链首三个模型
# （agnes-3.0-flash 262k / ling-3.1-flash 262k / nemotron-3-ultra 1M）
# context window 平均值 507k 的 25%，留足余量给一次大工具返回（read_careers
# 约 5.4k、read_job_gap 最大约 7.1k）。压缩只动本进程内存，不落盘。
COMPACT_THRESHOLD = 128_000
COMPACT_KEEP_TURNS = 6  # 压缩时保留最近 6 轮原文（12 条）


COMPACT_PROMPT = """把一段对话压缩成摘要，供同一段对话后续继续使用。只输出摘要正文，
不要 markdown 代码块，不要前言后记。

必须保留三件事，缺一不可：

1. **未完成的事**：进行中的追问停在第几题、已经问到什么、哪些文件读了一半、
   正在等用户回答什么。丢了这条，对话会从中间断掉，用户不知道该接哪。
2. **用户的事实性陈述**：他亲口说的经历、项目、数字、偏好、约束。
   这些还没持久化，是只存在于这段对话里的信息，丢了就再也找不回。
3. **已经确认的结论**：查过哪些文件、得到什么判断、否掉了哪些选项。

不要保留寒暄、致谢、重复的问答骨架。摘要精简凝练，保留有用信息。

这是压缩产物，不是用户发言。需要原文细节时用工具重新读文件，不要凭摘要猜。"""


def _compact(history: list[dict]) -> None:
    """历史超阈值时压成一条摘要，原地改写 history。

    摘要以 user 身份注入而不是 system：system prompt 只有一份、保持单一事实源，
    也和 Claude Code / Codex 的做法一致。

    压缩失败不抛：压缩是优化，不该让这一轮问答整个失败，原样保留历史。
    """
    keep = COMPACT_KEEP_TURNS * 2
    if len(history) <= keep:
        return
    old, recent = history[:-keep], history[-keep:]
    transcript = "\n".join(f"{'用户' if m['role'] == 'user' else 'Argus'}：{m['content']}" for m in old)
    try:
        msg = call_llm([
            {"role": "user", "content": COMPACT_PROMPT},
            {"role": "user", "content": f"<对话记录>\n{transcript}\n</对话记录>"},
        ])
        summary = (msg["content"] or "").strip()
    except RuntimeError as e:
        logger.warning("compact 失败，保留原历史：%s", e)
        return
    if not summary:
        return
    logger.info("compact: %d 轮 → 1 条摘要(%d 字) + 最近 %d 轮", len(old) // 2, len(summary), COMPACT_KEEP_TURNS)
    history[:] = [{"role": "user", "content": f"<此前对话摘要>\n{summary}\n</此前对话摘要>"}, *recent]


def auto_compact(history: list[dict]) -> list[dict]:
    """超阈值先压缩，再返回可放进请求的历史。原地改写 history。"""
    if _input_tokens(history, None) > COMPACT_THRESHOLD:
        _compact(history)
    return list(history)
"""Agent 工具的实现。注册表（TOOLS / READERS）在 chat.py。

划分依据是**这块代码归哪个领域、谁消费它**：被 LLM 当作 tool call 调用的
函数，实现全在这里——它们的服务对象是模型调用，不是某个 HTTP 路由。
chat.py 决定「有哪些工具、怎么注册」，tools.py 决定「工具被调用时干什么」。

- 四个只读工具：直接读 data/ 下的文件，不经 jobs.py 的路由函数
- 简历三个工具：建 / 读 / 评，见 resume.py。**没有写简历的工具**——他自己改；
  @tool 外壳统一收异常
- search_jobs：搜岗位，唯一会写 data/ 事实源的暂用工具，暂时停用没注册，实现留着
- auto_compact：会话内存的 token 阈值压缩，由 /api/chat 在发请求前调，
  **不进 TOOLS**——压缩若是模型可选行为，模型不调就不压，阈值形同虚设

data/ 是事实源，工具只读不写。新增工具在此实现，再到 chat.py 注册。
"""

import json
import logging

from common import call_llm, clean_llm_json, _input_tokens
from persona import get_persona
from jobs import gaps_by_job, normalize, save_snapshot, CAREERS, GAPS
# 领域侧叫 copy_from_persona / critique，工具侧带 resume 后缀。两边不同名，
# 工具函数体里调领域函数时才不会被自己遮住。
from resume import (
    CAREERS,
    RESUME_DIR,
    copy_from_persona,
    critique,
)
from utils import load_file, tool
from crawler import fetch_liepin_html, parse_jobs, fetch_boss_recommendations, fetch_boss_details

logger = logging.getLogger("argus.tools")


# ── 四个只读工具 ─────────────────────────────────────────────────────────


@tool
def read_persona() -> dict:
    """读用户**最初上传的那份**履历与求职意向。没上传过时回 empty，让模型直接问用户要简历。

    与简历（read_resume）分家：他上传的是初稿，之后他在 Resume 页自己改的是另一份文件，
    两边会分叉。用户改完简历后，这里仍是旧版——不要拿它当"他现在的简历"说话。
    """
    data = get_persona()
    if not data:
        return {"status": "empty", "detail": "用户还没上传简历"}
    return {"status": "ok", "persona": data}


@tool
def read_careers() -> dict:
    """Career 全量：定位、归属判据、能力清单、成员岗位。6 个 Career 一次读完，
    模型才能横向比较。只回 careers 数组，generated_at 之类的元信息对回答没用。"""
    if not CAREERS.exists():
        return {"status": "error", "detail": "还没有 careers.json"}
    doc = json.loads(CAREERS.read_text(encoding="utf-8"))
    return {"status": "ok", "careers": doc.get("careers", [])}


@tool
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


@tool
def read_gap(job_id: str) -> dict:
    """单个岗位的完整解读：每条要求与 persona 的匹配状态、缺什么、简历里的证据。
    带上跑分析时的求职意向快照——不然模型无从判断「对齐」是对齐到什么。"""
    row = gaps_by_job().get(job_id)
    if not row:
        return {"status": "error", "detail": f"没有 {job_id} 的解读"}
    return {"status": "ok", **row}


# ── JD 匹配 ───────────────────────────────────────────────────────────────
# 用户在 chat 里贴一份 JD，比对 persona 判断是否合适，并给招聘平台开场白。
# prompt 抄自 scripts/cluster_jobs.py 的 ANALYZE_PROMPT（openning 逐字保留），
# 那边是批量岗位全量报告，这里只要判断 + 开场白，故裁到这两个字段。

JD_MAX_CHARS = 1600

ANALYZE_JD_PROMPT = """
<Role>
你是深度求职匹配与策略分析专家。对候选人 Persona 与用户贴来的一份岗位 JD 做精细化能力比对，判断是否合适，并给出打招呼开场白。
</Role>

<Principles>
1. 拒绝盲目压缩：JD 中的特定工具、业务场景、具体指标必须全量提取，不得抽象为泛泛词汇。
2. 以终为始：先推理该岗位真正需要什么能力，再与 Persona 逐项比对。
3. 证据客观锚定：只依据 Persona 真实经历，迁移性能力须标注迁移路径，不得假想未列出的能力。
4. 意向与能力隔离：地点、薪资等仅作硬性标记。
</Principles>

<Output_Constraint>
必须且仅输出合法 JSON 字符串，不得含 Markdown 代码块标记或任何前言后记。结构：
{
  "cluster_category": "apply_now | learn_then_apply | build_evidence_then_apply | develop_then_apply | deprioritize",
  "confidence": "high | medium | low",
  "matching_rationale": "string (总体匹配度与分类依据的完整逻辑阐述)",
  "openning": "string (在招聘平台上对对方打招呼的开场白，以“你好，我有多年互联网商业数据分析经验，擅长指标量化归因与精细化运营策略，对贵岗很感兴趣，期待与您沟通“为 base，根据岗位核心需求和自身优势进行个性化改写，字数控制在 50 字左右，表达专业，平视对方，避免热切，避免套话)"
}
</Output_Constraint>
"""


@tool
def analyze_jd(jd: str) -> dict:
    """用户贴一份 JD 时调它：判断与用户 Persona 是否匹配，并给一段招聘平台开场白。"""
    jd = (jd or "").strip()
    if not jd:
        return {"status": "error", "detail": "JD 为空"}
    persona = json.dumps(get_persona(), ensure_ascii=False, indent=2)
    material = (
        f"<Candidate_Persona>\n{persona}\n</Candidate_Persona>\n\n"
        f"<Target_JD>\n{jd[:JD_MAX_CHARS]}\n</Target_JD>"
    )
    msg = call_llm(
        [{"role": "user", "content": ANALYZE_JD_PROMPT},
         {"role": "user", "content": material}],
        temperature=0.1,
        max_tokens=8192,
    )
    return {"status": "ok", **clean_llm_json(msg["content"])}


# ── 简历三段 ───────────────────────────────────────────────────────────────
# 触发方式是 agent 自己调 start_resume——没有按钮。用户什么时候想投哪个职能，该由
# 对话里判断出来，不该被某个 UI 动作决定。
#
# 这里只有「建 / 读 / 评」三个动作，没有「写」。改简历是用户自己在 Resume 页做的事：
# LLM 不碰这份文件，apply_patch 那一层留给用户手改时走（见 chat.py 的 /api/resumes/*/edits）。


@tool
def start_resume(career_id: str) -> dict:
    """切到「为这个职能准备简历」模式。返回职能要求 + 现有材料的提纲，
    够 agent 立刻开始对着问，不用再回头翻别的文件。"""
    careers = load_file(CAREERS)["careers"]
    if career_id not in {c["career_id"] for c in careers}:
        raise KeyError(f"没有 {career_id} 这个 Career，现有的有：{' '.join(c['career_id'] for c in careers)}")
    career = next(c for c in careers if c["career_id"] == career_id)
    persona = get_persona()
    out = {
        "status": "ok",
        "career": {k: career.get(k) for k in ("career_id", "name", "positioning")},
        "capabilities": career.get("capabilities", []),
        "已知的经历": [
            {"公司": w.get("company"), "职位": w.get("role"),
             "起止": f"{w.get('start_date', '')}–{w.get('end_date', '')}",
             "已写的项目": [p.get("name", "") for p in w.get("projects", [])]}
            for w in persona.get("work_history", [])
        ],
        "已知的技能": persona.get("skills", []),
        "提醒": "以上是他自己写的，只写了自以为拿得出手的部分。据此开始提问。",
    }
    # 没有简历就先有一份：persona 去掉求职意向，逐字拷贝，不调 LLM。
    if load_file(RESUME_DIR / f"{career_id}.json"):
        out["简历"] = "已存在，直接读它继续"
    else:
        copy_from_persona(career_id)
        out["简历"] = "已按 persona 建好底稿（去掉求职意向）。他不提就别催——改是他自己的事"
    return out


@tool
def read_resume(career_id: str) -> dict:
    """读简历全文。没建过就报错——先调 start_resume 建一份。

    这份是**他自己改过的当前版本**，跟 read_persona（最初上传的初稿）不是一回事。
    """
    saved = load_file(RESUME_DIR / f"{career_id}.json")
    if not saved:
        raise FileNotFoundError(f"{career_id} 还没有简历，先调 start_resume 建一份")
    # 剥掉 edits，同 resume.body：它是改动历史不是简历材料，喂回去模型会照着
    # 上次的 path 再改一遍。前端不受影响——它走 chat._resume_card，那份要留着。
    return {"status": "ok",
            "resume": {k: v for k, v in saved["resume"].items() if k != "edits"}}


@tool
def critique_resume(career_id: str) -> dict:
    """筛简历。返回筛选结论、可改的地方、以及只能继续挖的缺口。

    history 留档但不回喂：全量带进上下文会按筛选次数线性涨，且旧报告里的 path 是
    照着当时的简历写的，照着改会打错位置。只给最新一份和次数。

    报告是**写给他看的建议**，不是待执行的改动——他自己动手改，模型不碰他的文件。
    """
    review = critique(career_id).get("review", {})
    return {"status": "ok", **{k: v for k, v in review.items() if k != "history"},
            "历次筛选次数": len(review.get("history", []))}


# search_boss_jobs 暂时停用：没注册进 chat.TOOLS，实现留着，想开回来把它加进
# TOOLS 即可。它是唯一会写 data/ 事实源的已注册工具（落 boss_jobs.json 覆盖快照）。
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
        ], max_tokens=8192)
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
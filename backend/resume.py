"""Resume 领域：针对单个 Career 的简历产出（workflow.md 的 S4）。

简历是**用户的文件**，不是每次重新生成的产物。进模式时先把 persona 去掉求职意向
原样拷过来当底稿——不调 LLM，简历本来就该是他那份履历。之后他自己在 Resume 页动手改，
本模块不替他写一个字。

**AI 在简历上只剩两个动作：问和评。** 问是挖掘追问（DIRECTIVE 管），评是筛简历
（critique）。合并、改写这两步已经摘掉——改简历是用户的权利，不是模型的能力。

critique **只拿到职能要求和简历成品**，没有 persona——它模拟的不是面试，是简历关：
筛简历的人在决定要不要把这个人叫进面试间，倒序扫、前 15 秒定生死，**他不追问**。

读文件、打 patch 都用 utils.py 的通用函数，这里不重复造。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from common import GEMINI_MODEL, ask_json_async
from persona import get_persona
from utils import apply_patch, list_store_keys, load_file, save_file_async

ROOT = Path(__file__).resolve().parents[1]
CAREERS = ROOT / "data" / "careers.json"
RESUME_DIR = ROOT / "data" / "resumes"

# persona 的求职意向三个字段不属于简历。拷贝时剔掉。
TARGET_KEYS = ("target", "target_base", "target_salary")

# 筛简历钉 gemini。容灾链链首那几个免费小模型判不准——「够吸引我」是个需要判断力的活，
# 交给弱模型等于没筛。（pinned 只影响第一次尝试，失败仍照常降级，common.call_llm。）
MODEL = GEMINI_MODEL

# 切到准备简历模式时追加在 system prompt 后面。它管的是**怎么跟人聊**，不是简历
# 长什么样——那是 critique 自己的 prompt 的事。
DIRECTIVE = """## 当前任务：为「{career}」准备一份简历

简历已经有一份了，就是他自己传的那份去掉求职意向。**简历是他的，你不要动它。**

他的履历是他自己写的，只写了自以为拿得出手的部分。**没写的不代表他没有**——那些他自己
觉得不值得写、但其实很对口的经历，正是这份简历里最值钱的部分，也是本项目存在的理由。

- **一条条对着问**：这个职能的每条能力要求，哪些他完全没材料、哪些有但没写出来。
- **问细节，不问确认。**「你熟不熟 SQL」必然得到「熟」，零信息量。要问「最近一次写 SQL
  是什么时候、处理了什么表、多大数据量」。**编不出来的具体性本身就是护栏。**
- **不要拿你已经知道的当提问前提。** 他简历里写着「A/B 实验」，就别问「你做过 A/B 实验
  吗」——要去问那次实验怎么设计的、结论怎么来的、最后谁做了什么决定。
- **「没有」也要记下来**：它防止你重复追问，也让简历里哪些是真空白一目了然。
- 一轮最多三个问题，一次问一个。他答完可能反悔要改前面的，按最新的算。

挖到的就讲给他听，说清楚是哪段经历、他说了什么。**接下来怎么写进简历是他自己的事**——
他会在 Resume 页亲手改。不要替他改，也不要问要不要帮他改。

**不要自己评价简历写得好不好**——判断权在筛的那步。你要做的是问出他还没说的东西。"""


async def copy_from_persona(career_id: str) -> dict:
    """底稿：persona 去掉求职意向，原样落盘。**不调 LLM、不动一个字。**

    简历不是生成出来的，是他那份履历去掉求职意向——本来就该先有一份。后面每一次
    改动都是在这份上打 patch，所以这一步必须逐字来自 persona。
    """
    persona = {k: v for k, v in get_persona().items() if k not in TARGET_KEYS}
    if not persona.get("work_history"):
        raise ValueError("还没有 persona，先让他传一份简历")
    career = {c["career_id"]: c for c in load_file(CAREERS)["careers"]}[career_id]
    return await save_file_async(RESUME_DIR / f"{career_id}.json", {
        "career_id": career_id,
        "career_name": career["name"],
        "updated_at": time.strftime("%Y-%m-%d %H:%M"),
        "resume": {**persona, "edits": []},
    })


async def apply_edits(career_id: str, ops: list, reason: str) -> dict:
    """改简历正文的唯一入口：只动点名的条目，改完记一笔。筛出来的报告不碰。

    **唯一的调用方是用户在 Resume 页的手改**（Worker 侧 api_write.py）：
    前端表单天生知道「用户改的是 /work_history/0/projects/1/description」，把字段换算成
    ops 发过来，这里照单落盘。LLM 那三个写工具摘掉之后，AI 不再碰这个文件。

    load→patch→save 是读改写：单用户下同 sid 串行，竞争不可达；真有多端
    并发那天，上 R2 的条件写（etag）而不是在这里加锁。
    """
    path = RESUME_DIR / f"{career_id}.json"
    saved = load_file(path)
    if not saved:
        raise FileNotFoundError(f"{career_id} 还没有简历")
    # edits 由下面无条件覆盖，谁要是 patch 了它，改动会静默消失。改成报错。
    if any(op.get("path") == "/edits" or str(op.get("path", "")).startswith("/edits/") for op in ops):
        raise ValueError("edits 是系统记的账，不许 patch；改简历内容，不要动改动历史")
    patched, applied = apply_patch(saved["resume"], ops)
    # 空 ops 是「这一趟什么都没改」，不是一次改动。记一笔进去会让版本号凭空多一个，
    # 「改过 N 处」也就不再是能读的数字了。
    if not applied:
        return saved
    patched["edits"] = [*saved["resume"].get("edits", []), {
        "at": time.strftime("%Y-%m-%d %H:%M"), "reason": reason, "applied": applied,
    }]
    return await save_file_async(path, {**saved, "updated_at": time.strftime("%Y-%m-%d %H:%M"), "resume": patched})


def resume_paths() -> list[Path]:
    """简历文件清单。Worker 无文件系统，glob 换成 store key 枚举；离线仍 glob。

    两条路都只回「哪些 career 有简历」。Worker 侧 set 非空即 Worker 模式；
    store 空（离线）时不拦，直接走 glob，行为与从前一致。
    """
    keys = list_store_keys("resumes/")
    if keys:
        return [RESUME_DIR / Path(k).name for k in sorted(keys)]
    return sorted(RESUME_DIR.glob("*.json")) if RESUME_DIR.exists() else []


def list_resumes() -> list[dict]:
    """简历索引：Resume 页列表与 Career 页软链共用。只要摘要，正文走单份读。

    带 edits_count 是因为简历现在是用户自己的文件，「我改到第几版」是他的劳动记录，
    不是 AI 的评语——Resume 页上值得显示。评语（verdict / one_line / needs_mining）
    一并带上，Career 页的软链要显示它们。
    """
    out = []
    for path in resume_paths():
        doc = load_file(path)
        review = doc.get("review") or {}
        out.append({k: doc.get(k, "") for k in ("career_id", "career_name", "updated_at")}
                   | {k: review.get(k, "") for k in ("verdict", "one_line")}
                   | {"needs_mining": review.get("needs_mining", []),
                      "edits_count": len(doc.get("resume", {}).get("edits", []))})
    return out


async def ensure_all() -> list[dict]:
    """补齐每个 Career 的底稿，再返回索引。

    简历不是「谈到了才建」的东西——每个 Career 都有一份，用户在 Resume 页挑一份去改。
    补的动作跟 start_resume 里那次是同一个 copy_from_persona：逐字拷 persona、零 LLM。
    已经在的不动，用户改过的那份永远不会被覆盖。

    persona 还没有（他没上传过简历）时只返回已有的，不补——补出来是空壳。
    """
    # load_file 而非 CAREERS.exists()：Worker 的文件不存在性检查永远为假，
    # exists() 会让 ensure_all 静默返回空列表。同样理由，逐份存在性也查 load_file。
    careers = (load_file(CAREERS) or {}).get("careers", [])
    if get_persona().get("work_history"):
        for career in careers:
            if not load_file(RESUME_DIR / f"{career['career_id']}.json"):
                await copy_from_persona(career["career_id"])
    return list_resumes()


def document(career_id: str) -> dict | None:
    """单份简历的对外视图：正文 + 文档自己的元信息 + 筛选报告。

    career_id / career_name / updated_at 存在**文档层**、不在 resume 层（见 copy_from_persona），
    但 Chat 的卡片和 Resume 页的详情都要显示它们。在这儿拼一次，别让每个调用方自己记得补。
    """
    saved = load_file(RESUME_DIR / f"{career_id}.json")
    if not saved:
        return None
    return ({**saved["resume"]}
            | {k: saved.get(k, "") for k in ("career_id", "career_name", "updated_at")}
            | {"review": saved.get("review") or {}})


def body(saved: dict) -> str:
    """给 LLM 看的简历正文，剥掉 edits。

    edits 是系统记的账，不是简历材料——`applied` 还是一串 path 字符串，喂进去模型
    会照着上次的改动再改一遍。一次收尾序列里简历正文要发四份，每份都拖着它，30 次
    改动后就是 18KB 纯噪音，而且单调增长、删不掉。

    chat 拼 system prompt 时也用它——它和 critique 看到的必须是同一份正文。
    """
    return json.dumps({k: v for k, v in saved["resume"].items() if k != "edits"},
                      ensure_ascii=False, indent=2)


async def critique(career_id: str) -> dict:
    """筛简历。输入只有「职能要求 + 简历成品」，没有原始履历。"""
    path = RESUME_DIR / f"{career_id}.json"
    saved = load_file(path)
    career = {c["career_id"]: c for c in load_file(CAREERS)["careers"]}[career_id]

    report = await ask_json_async("""你在筛简历。

候选人投的那个职能，就是你手上「职能要求」里这个。你有两样东西：它的能力要求（这就是
你的口味），以及候选人的简历。**你没有他的原始履历，也不需要。**

**你不追问，也不会追问。** 你还没给他面试机会，你正在决定要不要给。追问是拿到面试之后
才发生的事，不是现在的事。

# 你在看什么

筛简历阶段只回答一个问题：**这人看着像不像能干这活的。** 具体地：

1. **倒序扫。** 先看最近这段工作：待了多久、什么规模的公司、做的什么。
2. **前 15 秒定生死。** 大多数人扫到第三段就划走了。他的第一屏是什么，直接决定结果。
3. **找信号。** 有没有能对上门要求的**具体东西**，而不是「搭建了体系」「提升了效率」。
4. **排除。** 职责说不清、压根没有他要的东西，直接否了。空档看长度：三个月和两年不是
   一回事，短的只要说清这段时间在做什么就往下走。

不要评价他文笔好不好，也不要评价话说得圆不圆。**只判断：你会不会把他放进面试间。**

# 输出

只输出合法 JSON，不要 markdown 代码块、不要解释：

{
  "verdict": "进面试 | 边缘 | 不进",
  "first_screen": "第一屏读下来你看到的是什么，一两句",
  "fixable": [{"what": "", "why": "", "path": "被点名条目的 path"}],
  "needs_mining": [{"capability": "", "why": "", "ask": ""}],
  "one_line": "一句话结论，写给候选人看，要直说"
}

`fixable` 与 `needs_mining` 的分界是这份报告的承重处：前者改措辞就能解决，后者是简历里
根本没有这个东西、只能回去继续挖的。分错了，下一步的重写会去编。`path` 必须照抄简历里
真实存在的路径，填不出来的那条就归到 needs_mining。`verdict` 无论给什么，`fixable` 与
`needs_mining` 合起来至少一条：空手而归的话，下一步就没有可执行的东西，只能拿着同一份
简历再问一遍。""", [
        "<职能要求>\n" + json.dumps(career, ensure_ascii=False, indent=2) + "\n</职能要求>",
        "<简历>\n" + body(saved) + "\n</简历>",
    ], temperature=0.3, model=MODEL)

    now = time.strftime("%Y-%m-%d %H:%M")
    latest = {"at": now, **{k: report.get(k, "") for k in
                            ("verdict", "first_screen", "fixable", "needs_mining", "one_line")}}
    # 历次筛选留档：改完再看一次，结论有没有变，是唯一能判断改得有没有用的证据。
    return await save_file_async(path, {**saved, "review": {"model": MODEL, **latest,
        "history": [*(saved.get("review") or {}).get("history", []), latest]}})
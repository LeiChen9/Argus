"""岗位聚类：把 boss_jobs.json 的岗位按**职能**划成岗位族。

对应 workflow.md 的 S1。纯岗位侧，不读 persona.json——聚类时带上 Persona
会让分类法向用户已经会的东西收敛，于是永远看不见邻近机会（workflow.md §2 S1）。

一次 LLM 调用读完全部 JD，产出：
  - 每个族的定位、核心能力要求、归族判据
  - job_id → family_id 的映射（必须落盘，见 workflow.md §2 S1）

输出 data/job_families.json 是**人可编辑的产物**：族定义和归族结果都是
后续 S2/S4/S5 的地基，重跑聚类会让族的边界漂移，所以不在每次调用时重算。

用法（项目根执行）：python3 scripts/build_families.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from common import active_chain, call_llm, clean_llm_json  # noqa: E402

JOBS_PATH = ROOT / "data" / "boss_jobs.json"
OUT_JSON = ROOT / "data" / "job_families.json"

JD_MAX_CHARS = 1200


def build_job_block(job: dict) -> str:
    """一个岗位一块，带 id 便于模型回填归族结果。

    JD 截断到 JD_MAX_CHARS：当前 30 岗合计约 1.4 万字符，一次调用读得完，
    但岗位涨到几百个时不截断会把单次上下文顶爆，而族划分只需要职责与要求，
    不需要后面的福利待遇段落。
    """
    jd = (job.get("jd") or "")[:JD_MAX_CHARS]
    return (
        f"<job id=\"{job['id']}\">\n"
        f"title: {job.get('title', '')}\n"
        f"company: {job.get('company', '')}\n"
        f"salary: {job.get('salary', '')}\n"
        f"location: {job.get('location', '')}\n"
        f"tags: {job.get('tags', '')}\n\n"
        f"{jd}\n"
        f"</job>"
    )


CLUSTER_PROMPT = """
<Role>
你是**岗位分类与职业能力建模专家**。任务是把给定的一批真实岗位 JD 划成若干个
**岗位族（job family）**，并为每个族定义其定位与核心能力要求。
</Role>

<Principles>
1. **job title 只作为辅助参考，主要判据是 JD 正文的职责与能力要求。** title 是各公司自定的
   命名习惯，有可能与实际职责错位。因此**先只读 JD 正文**，
   对每个岗位先推断出「它实际承担什么、被考核什么、需要什么能力」，再据此归族。
   同一族的充分条件是**岗位职责与能力要求一致**。
2. **不按行业切。** 同一个真实职能（如经营分析）在游戏、电商、本地生活里都成立，
   应归入同一族。反过来，行业相同但职能不同（电商供应链的商业分析 vs 电商BI
   工程师）不得归入同一族。
3. **族数服从内聚性，不预设目标数量。** 要求族的定义清晰，不互相重叠。
   若某个岗位与所有已有族都不匹配，则**新建一个族**，不要硬塞进最像的那个。
   避免族的核心能力定义被污染。**族内只有一个岗位也是合法的**——与其把
   一个边缘岗位塞进错误的族、污染那个族的能力定义，宁可单开一个单岗族。
4. **能力要求用岗位原文支撑。** 每条 capability 必须能在至少一个成员岗位的
   JD 中找到依据，不得引入 JD 里没有的行业黑话。
</Principles>

<Workflow>
1. **逐个岗位先做职责推断** 对每个岗位写一句话：这个岗位实际
   对什么负责、被考核什么、需要什么能力。title 只作为参考，先形成判断再看
   title 复核，而不是反过来。
2. 通读全部推断结果，按「职责与能力要求是否一致」归拢岗位。
3. 为每个族确定 name（职能名，不带行业前缀）、positioning、membership_criteria。
4. 抽取该族的 capabilities，按**职能本身**判断什么重要、什么次要、
   什么是加分项——依据是该能力在这个职能的日常职责中处于什么位置（职能职责主要从JD；次要从对职能的理解来推断）
   而非它在多少个成员岗位的 JD 里出现过。采样不均匀，出现次数不能完全代表重要性。
5. 把每个岗位放进**它所属那个族**的 jobs。**每个岗位必须恰好出现一次，
   不允许遗漏，也不允许重复。**
</Workflow>

<Output_Constraint>
必须且仅输出合法 JSON，不得包含 Markdown 代码块标记或任何前言后记。结构如下：

{
"families": [
    {
      "family_id": "F1",
      "name": "string (职能名，如「经营分析」)",
      "positioning": "string (这个族在职业路径上的定位与典型职责重心)",
      "membership_criteria": "string (什么样的岗位属于这一族，判据要可执行；按职责与能力要求描述，不要按 title 字面匹配)",
      "capabilities": [
        {
          "capability": "string (能力要求本身)",
          "level": "core | important | bonus (按该能力在职能中的重要性判断)",
          "jd_evidence": "string (支撑这条要求的 JD 原文片段或要点)"
        }
      ],
      "jobs": [
        {
          "job_id": "string",
          "company": "string",
          "title": "string",
          "belongs_note": "string (该岗位为何属于本族；若 title 与实际职能不符，在此说明)"
        }
      ]
    }
  ]
}
</Output_Constraint>
"""


def build_messages(jobs: list[dict]) -> list[dict]:
    """instruction 与素材分成两条消息。

    理由同 cluster_jobs.py：CLUSTER_PROMPT 里含大量 JSON 花括号，
    用 .format() 会撞 KeyError；指令与数据分开，模型对「照这个格式输出」
    和「照这批内容分类」的注意力分配也更干净。
    """
    blocks = "\n\n".join(build_job_block(j) for j in jobs)
    material = f"<Jobs>\n{blocks}\n</Jobs>\n\n共 {len(jobs)} 个岗位。"
    return [
        {"role": "user", "content": CLUSTER_PROMPT},
        {"role": "user", "content": material},
    ]


def build_assignment(result: dict) -> dict[str, str]:
    """从各族成员推出 job_id → family_id 反查表。

    归属不单独存：岗位出现在哪个族的 members 里，它就属于哪个族。
    反查表是纯派生物，用时现算，不落盘。
    """
    return {
        j["job_id"]: f["family_id"]
        for f in result.get("families") or []
        for j in f.get("jobs") or []
    }


def verify(result: dict, jobs: list[dict]) -> None:
    """校验每个输入岗位都恰好归入一个族。

    对不上就不能落盘：漏掉的岗位会在下游静默消失——S2 不会分析它，
    页面上也不显示，却没有任何地方报错。
    """
    ids = [
        j.get("job_id")
        for f in result.get("families") or []
        for j in f.get("jobs") or []
    ]
    expected = {j["id"] for j in jobs}
    if set(ids) != expected or len(ids) != len(expected):
        raise RuntimeError(
            f"job_id 对不上：输入 {len(expected)} 个，"
            f"收到 {len(ids)} 个（其中唯一 {len(set(ids))} 个）"
        )


def main() -> None:
    store = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    jobs = [j for j in store["jobs"].values() if j.get("jd")]

    chain = [i["name"] for i in active_chain()]
    print(f"岗位 {len(jobs)} 个 · 容灾链 {' → '.join(chain)}")

    t0 = time.perf_counter()
    msg = call_llm(build_messages(jobs), temperature=0.2)
    result = clean_llm_json(msg["content"])
    verify(result, jobs)

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "model": msg["model"],
        "source_jobs_at": store.get("updated_at", ""),
        "total_jobs": len(jobs),
        "families": result["families"],
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"耗时 {time.perf_counter() - t0:.1f}s · {msg['model']} → {OUT_JSON.name}\n"
        + "\n".join(
            f"  {f['family_id']}: {f['name']} · "
            f"{len(f.get('capabilities') or [])} 条能力 · "
            f"{len(f.get('jobs') or [])} 个岗位"
            for f in result["families"]
        )
    )


if __name__ == "__main__":
    main()

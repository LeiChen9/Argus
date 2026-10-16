"""岗位聚类：把 boss_jobs.json 的岗位按**职能**划成 Career。

对应 workflow.md 的 S1。纯岗位侧，不读 persona.json——聚类时带上 Persona
会让分类法向用户已经会的东西收敛，于是永远看不见邻近机会（workflow.md §2 S1）。

一次 LLM 调用读完全部 JD，产出：
  - 每个 Career 的定位与归属判据
  - job_id → career_id 的映射（必须落盘，见 workflow.md §2 S1）

**Career 上限 MAX_CAREERS 个，允许丢弃归不进任何 Career 的岗位。**
理由（2026-10-16 定）：招聘平台只让留 3 份简历，Career 超过 3 个用户也看不过来；
宁可少而内聚，不要多而互相污染。

输出 data/careers.json 是**人可编辑的产物**：Career 边界一重跑就漂，所以
「切边界」与「补能力」分成两步——本脚本只切边界，capabilities 字段整个
不出现，由 scripts/extract_capabilities.py 逐个 Career 另跑一次补齐。那次调用
读的是**磁盘上当前的边界**，因此边界可以先按人读的判断手改，再抽能力。

用法（项目根执行）：python3 scripts/build_careers.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import os
from common import active_chain, call_llm, clean_llm_json  # noqa: E402

# 离线管线服务于单个账号：产物落 data/<用户>/，与 R2 上的命名空间一致。
# 默认 lbb；给别的账号跑离线脚本就 ARGUS_USER=xxx python3 …（Worker 侧由 cookie 决定）。
USER = os.environ.get("ARGUS_USER", "lbb")

JOBS_PATH = ROOT / "data" / USER / "boss_jobs.json"
OUT_JSON = ROOT / "data" / USER / "careers.json"

JD_MAX_CHARS = 1200

# Career 数量上限。见模块 docstring：3 份简历的平台限制 + 用户的注意力预算。
MAX_CAREERS = 3


def build_job_block(job: dict) -> str:
    """一个岗位一块，带 id 便于模型回填归属结果。

    JD 截断到 JD_MAX_CHARS：当前 30 岗合计约 1.4 万字符，一次调用读得完，
    但岗位涨到几百个时不截断会把单次上下文顶爆，而划分 Career 只需要职责与
    要求，不需要后面的福利待遇段落。
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
你是**岗位分类专家**。任务是把给定的一批真实岗位 JD 划成若干个
**Career**，并为每个 Career 定义其定位与归属判据。你只切边界，
不列能力项——能力由另一次调用按 Career 抽取。
</Role>

<Principles>
1. **job title 只作为辅助参考，主要判据是 JD 正文的职责与能力要求。** title 是各公司自定的
   命名习惯，有可能与实际职责错位。因此**先只读 JD 正文**，
   对每个岗位先推断出「它实际承担什么、被考核什么、需要什么能力」，再据此归类。
   同一 Career 的充分条件是**岗位职责与能力要求一致**。
2. **不按行业切。** 同一个真实职能（如经营分析）在游戏、电商、本地生活里都成立，
   应归入同一 Career。反过来，行业相同但职能不同（电商供应链的商业分析 vs 电商BI
   工程师）不得归入同一 Career。
3. **Career 数量上限 3 个，宁少勿滥。** 内聚性优先于覆盖率：先把职责与
   能力要求最一致的两三类岗位归拢，定义要清晰、不互相重叠。**允许丢弃
   一部分归不进任何 Career 的岗位**——不进 careers.json，也不报错。不得
   为了凑数新建第 4 个 Career，也不得把边缘岗位塞进最像的那个 Career、
   污染它的能力定义。
</Principles>

<Workflow>
1. **逐个岗位先做职责推断** 对每个岗位写一句话：这个岗位实际
   对什么负责、被考核什么、需要什么能力。title 只作为参考，先形成判断再看
   title 复核，而不是反过来。
2. 通读全部推断结果，按「职责与能力要求是否一致」归拢岗位。
3. 为每个 Career 确定 name（职能名，不带行业前缀）、positioning、membership_criteria。
4. 把每个岗位放进它所属的那个 Career 的 jobs。**每个岗位至多出现一次；
   归不进任何现有 Career 的岗位直接丢弃**——不要新建超过 3 个的 Career，
   也不要硬塞进去。
</Workflow>

<Output_Constraint>
必须且仅输出合法 JSON，不得包含 Markdown 代码块标记或任何前言后记。结构如下：

{
"careers": [
    {
      "career_id": "C1",
      "name": "string (职能名，如「经营分析」)",
      "positioning": "string (这个 Career 在职业路径上的定位与典型职责重心)",
      "membership_criteria": "string (什么样的岗位属于这个 Career，判据要可执行；按职责与能力要求描述，不要按 title 字面匹配)",
      "jobs": [
        {
          "job_id": "string",
          "company": "string",
          "title": "string",
          "belongs_note": "string (该岗位为何属于这个 Career；若 title 与实际职能不符，在此说明)"
        }
      ]
    }
  ]
}
careers 数组最多 3 项。未被任何 Career 收录的岗位即为丢弃，不需要在输出中
另行列出。
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
    """从各 Career 成员推出 job_id → career_id 反查表。

    归属不单独存：岗位出现在哪个 Career 的 members 里，它就属于那个 Career。
    反查表是纯派生物，用时现算，不落盘。
    """
    return {
        j["job_id"]: f["career_id"]
        for f in result.get("careers") or []
        for j in f.get("jobs") or []
    }


def verify(result: dict, jobs: list[dict]) -> None:
    """校验：career 数 ≤ MAX_CAREERS；每个岗位至多归入一个 Career。

    不要求全覆盖——上限 3 个时边缘岗位允许丢弃（CLUSTER_PROMPT Principle 3），
    抓丢的岗位会在 main 里打印出来给人看。要防的是另一种静默错误：同一岗位
    重复出现两次，会让它在两个 Career 里都被当成成员。
    """
    careers = result.get("careers") or []
    if len(careers) > MAX_CAREERS:
        raise RuntimeError(f"career 数 {len(careers)} 超过上限 {MAX_CAREERS}")
    ids = [
        j.get("job_id")
        for f in careers
        for j in f.get("jobs") or []
    ]
    unknown = set(ids) - {j["id"] for j in jobs}
    if unknown or len(ids) != len(set(ids)):
        raise RuntimeError(
            f"job_id 对不上：未知 {sorted(unknown)}，重复 {len(ids) - len(set(ids))} 个"
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
        "careers": result["careers"],
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    kept = {j["job_id"] for f in result["careers"] for j in f.get("jobs") or []}
    dropped = [j["id"] for j in jobs if j["id"] not in kept]
    print(
        f"耗时 {time.perf_counter() - t0:.1f}s · {msg['model']} → {OUT_JSON.name}\n"
        + "\n".join(
            f"  {f['career_id']}: {f['name']} · "
            f"{len(f.get('jobs') or [])} 个岗位"
            for f in result["careers"]
        )
        + (f"\n丢弃 {len(dropped)} 个岗位: {', '.join(dropped)}" if dropped else "\n无丢弃岗位")
    )


if __name__ == "__main__":
    main()

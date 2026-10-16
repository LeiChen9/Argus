"""能力抽取：读磁盘上当前的 Career 边界，逐个 Career 补 capabilities。

对应 workflow.md 的 S1 第二步。边界由 build_careers.py 定、由人可改，本脚本
不重新划分。分开跑的理由：一次调用同时切边界和抽能力时两件事抢注意力，
实测同一批 30 岗跑两次，能力条数在 25 与 34 之间跳，边界也跟着漂。

每个 Career 一次独立调用，多个 Career 并发。只写 capabilities 相关键，
name / positioning / membership_criteria / jobs 原样保留。

用法（项目根执行）：python3 scripts/extract_capabilities.py
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from common import active_chain, call_llm, clean_llm_json  # noqa: E402
import os
from build_careers import build_job_block  # noqa: E402

# 离线管线服务于单个账号：产物落 data/<用户>/，与 R2 上的命名空间一致。
# 默认 lbb；给别的账号跑离线脚本就 ARGUS_USER=xxx python3 …（Worker 侧由 cookie 决定）。
USER = os.environ.get("ARGUS_USER", "lbb")

CAREERS_PATH = ROOT / "data" / USER / "careers.json"
JOBS_PATH = ROOT / "data" / USER / "boss_jobs.json"

MAX_WORKERS = 4

CAPABILITY_PROMPT = """
<Role>
你是**职业能力建模专家**。给定一个职能（Career）的全部成员 JD，产出这个职能的
能力要求清单。
</Role>

<Rules>
1. **每条能力必须有成员 JD 中的原文依据**，写进 jd_evidence。
2. **需要归纳。** 同一件事在不同 JD 中表述不同时，合并为一条，概括到能够涵盖
   其全部原始表述的程度。输出是能力清单，不是 JD 要点的罗列。
3. **归纳不得丢失信息。** 被合并的原始要求必须全部包含在合并后的那条之中，
   不得因概括而抹掉其中任何一项。
4. **level 由该能力在这个职能日常职责中的位置决定**，与它在多少个 JD 中
   出现过无关。
5. **不设条数。**
</Rules>

<Workflow>
1. 逐个 JD 提取其中提出的全部能力要求，逐条记录，不做合并。
2. 按是否为同一件事归并，概括成统一表述。
3. 为每条能力确定 level。
4. 用第 1 步的记录回查结果，确认每一条都已归入某项能力；未能归入的，
   在 coverage_note 中说明原因。
</Workflow>

<Output_Constraint>
必须且仅输出合法 JSON，不得包含 Markdown 代码块标记或前言后记：

{
  "capabilities": [
    {
      "capability": "string (概括后的能力要求)",
      "level": "core | important | bonus",
      "jd_evidence": "string (该条对应的 JD 原文片段)"
    }
  ],
  "coverage_note": "string (回查结论：归并情况与未归入项的原因)"
}
</Output_Constraint>
"""


def extract(career: dict, jobs: dict) -> tuple[list[dict], str]:
    ids = [j["job_id"] for j in career["jobs"]]
    block = "\n\n".join(build_job_block(jobs[i]) for i in ids)
    material = (
        f'<Career id="{career["career_id"]}" name="{career["name"]}">\n'
        f"positioning: {career.get('positioning', '')}\n"
        f"membership_criteria: {career.get('membership_criteria', '')}\n"
        f"成员 {len(ids)} 个岗位\n</Career>\n\n<Jobs>\n{block}\n</Jobs>"
    )
    msg = call_llm(
        [
            {"role": "user", "content": CAPABILITY_PROMPT},
            {"role": "user", "content": material},
        ],
        temperature=0.2,
    )
    out = clean_llm_json(msg["content"])
    return out["capabilities"], out["coverage_note"]


def main() -> None:
    store = json.loads(CAREERS_PATH.read_text(encoding="utf-8"))
    jobs = json.loads(JOBS_PATH.read_text(encoding="utf-8"))["jobs"]
    chain = [i["name"] for i in active_chain()]
    print(f"Career {len(store['careers'])} 个 · 容灾链 {' → '.join(chain)}")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(lambda c: extract(c, jobs), store["careers"]))

    for career, (caps, note) in zip(store["careers"], results):
        career["capabilities"] = caps
        career["coverage_note"] = note
    CAREERS_PATH.write_text(
        json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for career, (caps, _) in zip(store["careers"], results):
        print(f'  {career["career_id"]} {career["name"]}: {len(caps)} 条')
    total = sum(len(caps) for caps, _ in results)
    print(f"耗时 {time.perf_counter() - t0:.1f}s · 共 {total} 条 → {CAREERS_PATH.name}")


if __name__ == "__main__":
    main()
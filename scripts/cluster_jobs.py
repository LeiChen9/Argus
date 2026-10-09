"""岗位 × 简历差距分析。

读 data/boss_jobs.json 与 backend/persona.json，对**每个岗位单独**调一次 Gemini
做深度差距分析，把 LLM 的原始返回落盘到 data/job_gaps.json。

单 job 单次调用是刻意的：各岗位之间无依赖，这样每条分析都独立可复现、
单条失败只丢一个岗位，也让后续并行化不用改结构。

这里不做聚类。ANALYZE_PROMPT 已经给出 cluster_category 与 gap_canonical_tag，
下游要按 Gap 频次聚合时直接读落盘结果即可；在结果还没看过之前先定分组规则，
等于拿没验证的数据固化口径。

用法（项目根执行）：python3 scripts/cluster_jobs.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from common import GEMINI_MODEL, clean_llm_json, llm_client  # noqa: E402

PERSONA_PATH = ROOT / "backend" / "persona.json"
JOBS_PATH = ROOT / "data" / "boss_jobs.json"
OUT_JSON = ROOT / "data" / "job_gaps.json"

JD_MAX_CHARS = 1600


def build_resume_profile(persona: dict) -> str:
    """persona.json 原样转字符串。

    它已经是结构化 JSON，没有拍平的道理：拍平有损（项目的做法与成效会被我
    压成一句拼接），而 LLM 读 JSON 比读散文更准，工作年限它自己对日期做减法
    即可，不值得我在这里算——上一版就是算错在这。
    """
    return json.dumps(persona, ensure_ascii=False, indent=2)


ANALYZE_PROMPT = """
<Role>
你是**深度求职匹配与策略分析专家（Job Match & Interview Strategist）**。你的任务是对输入的候选人 Persona 与特定岗位 JD 进行无损、精细化的能力比对，生成可直接用于下游数据分析（如 Gap 聚合统计）与面试实战指导的结构化 JSON 报告。
</Role>

<Principles>
1. 拒绝盲目压缩：JD 中的特定工具（如 SQL/SAS/Python）、特定业务场景（如 信用卡/游戏发行/信贷）、具体指标（如 转化率/人均产能）必须全量提取，不得随意抛弃或抽象为泛泛词汇。
2. 判断与推理岗位要求：根据 JD 的内容以及岗位信息，深入思考当前岗位究竟需要候选人具备哪些能力，或者需要候选人负责什么工作，用以终为始的思路，推理出岗位的核心能力要求。
3. 证据客观锚定：评估必须严格依托 Persona 中的真实经历与成果。不得假想候选人具备未列出的能力；对具备迁移性的能力，必须明确标注迁移路径。
4. 下游聚类友好：对所有存在差距（non-proven）的项，必须按统一规范生成 **gap_canonical_tag**，以便系统在多岗位维度统计该 Gap 的覆盖频次。
5. 意向与能力隔离：地点、薪资等意向匹配仅作为硬性标记，不影响候选人“能力维度”的聚类分类。
</Principles>

<Workflow>
1. JD 需求全量解构：提取 JD 中的所有明确及隐含要求，保留完整业务场景与技术细节，区分核心权重（core/important/bonus）。
2. 逐项深度比对：遍历 Persona，进行证据寻找。标记匹配状态（proven/transferable/unknown/gap/blocked），记录匹配或缺失的完整事实细节。
3. 聚类与缺口标准化：根据 core 项匹配度确定岗位总体分类；针对所有非 proven 项，生成标准化的缺口标签（gap_canonical_tag）。
4. 行动矩阵输出：输出针对核心 gap 的高性价比补齐动作。
</Workflow>

<Gap_Tagging_Specification>
所有 gap_canonical_tag 必须遵循统一命名格式：`[分类]_[子领域/具体技术/业务场景]`
标准分类枚举：
- domain: 行业或业务认知缺口（如 domain_game_publishing, domain_credit_risk）
- tech: 明确的技术工具/建模缺口（如 tech_sas_modeling, tech_realtime_data）
- method: 分析方法论或运营框架缺口（如 method_causal_inference）
- evidence: 具备能力但缺乏对应场景的落地案例/数据成果证明（如 evidence_large_scale_team）
- constraint: 硬性门槛不匹配（如 constraint_degree_master, constraint_years_over_10）
</Gap_Tagging_Specification>

<Output_Constraint>
必须且仅输出合法的 JSON 字符串，不得包含 Markdown 代码块标记（如 ```json）或任何额外的前言后记。结构如下：

{
  "job_id": "string",
  "intent_match": {
    "location_status": "aligned | conflict | unknown",
    "salary_status": "aligned | above_target | below_target | unknown"
  },
  "requirements_deep_dive": [
    {
      "req_id": "R1",
      "jd_raw_context": "string (保留 JD 原始语义的完整描述，包含提及的场景、工具及指标)",
      "weight": "core | important | bonus",
      "match_status": "proven | transferable | unknown | gap | blocked",
      "persona_evidence": [
        "string (提取 Persona 中可支撑的完整项目、经验或技能描述，无则为空)"
      ],
      "gap_details": {
        "has_gap": true,
        "gap_canonical_tag": "string (严格遵循规范，如 domain_game_publishing)",
        "gap_description": "string (无损描述具体缺失了什么，如：缺乏游戏发行场景下的用户生命周期与营收拆解经验)",
        "bridge_difficulty": "easy | medium | hard"
      }
    }
  ],
  "decision": {
    "cluster_category": "apply_now | learn_then_apply | build_evidence_then_apply | develop_then_apply | deprioritize",
    "confidence": "high | medium | low",
    "primary_gap_tags": [
      "string (汇总所有阻碍直接投递的 gap_canonical_tag，用于跨岗位统计)"
    ],
    "matching_rationale": "string (对总体匹配度与分类依据的完整逻辑阐述)"
  },
  "interview_strategy": {
    "leverage_pitch": [
      {
        "strength_point": "string (应重点突出的岗位核心需求且用户优势的能力)",
        "mapped_project": "string (结合 Persona 中的哪段经历/项目证明)",
        "pitch_narrative": "string (面试时如何表述以展现极高匹配度)"
      }
    ],
    "defensive_script": [
      {
        "potential_concern": "string (面试官容易质疑的弱点/跨行业问题)",
        "mitigation_angle": "string (化解或引导至底层迁移能力的防守策略话术)"
      }
    ]
  },
  "actions": [
    {
      "target_gap_tag": "string (对应 primary_gap_tags 中的标签)",
      "task_description": "string (具体的弥补动作，如：整理一份离线外呼策略迁移至线上营销的分析框架Demo)",
      "expected_deliverable": "string (产出物或准备的案例故事)",
      "estimated_effort": "low_cost_fast | medium_effort | heavy_project"
    }
  ],
  "openning": "string (在招聘平台上对对方打招呼的开场白，以“你好，我有多年互联网商业数据分析经验，擅长指标量化归因与精细化运营策略，对贵岗很感兴趣，期待与您沟通“为 base，根据岗位核心需求和自身优势进行个性化改写，字数控制在 50 字左右，表达专业，平视对方，避免热切，避免套话)"
}
</Output_Constraint>
"""


def build_messages(job: dict, resume: str) -> list[dict]:
    """instruction 与素材分成两条消息。

    ANALYZE_PROMPT 里含大量 JSON 花括号，用 .format() 会撞 KeyError；而且
    指令与数据分开，模型对「照这个格式输出」和「照这批内容分析」的注意力
    分配也更干净。
    """
    jd = (job.get("jd") or "")[:JD_MAX_CHARS]
    material = (
        f"<Candidate_Persona>\n{resume}\n</Candidate_Persona>\n\n"
        f"<Target_Job>\n"
        f"id: {job['id']}\n"
        f"title: {job.get('title', '')}\n"
        f"company: {job.get('company', '')}\n"
        f"salary: {job.get('salary', '')}\n"
        f"location: {job.get('location', '')}\n"
        f"tags: {job.get('tags', '')}\n\n"
        f"JD:\n{jd}\n"
        f"</Target_Job>\n\n"
        f"job_id 必须原样回填为 {job['id']}。"
    )
    return [
        {"role": "user", "content": ANALYZE_PROMPT},
        {"role": "user", "content": material},
    ]


def analyze_one(job: dict, resume: str) -> dict:
    """单岗位调一次 LLM，返回原始 JSON。"""
    resp = llm_client().chat.completions.create(
        model=GEMINI_MODEL,
        messages=build_messages(job, resume),
        temperature=0.1,
    )
    return clean_llm_json(resp.choices[0].message.content)


def main() -> None:
    persona = json.loads(PERSONA_PATH.read_text(encoding="utf-8"))
    store = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    jobs = [j for j in store["jobs"].values() if j["jd"]]

    resume = build_resume_profile(persona)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "model": GEMINI_MODEL,
        "persona": persona,
        "total": len(jobs),
        "results": [],
    }
    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

        for i, job in enumerate(jobs, 1):
            t0 = time.perf_counter()
            payload["results"].append(
                {
                    "job": {
                        "id": job["id"],
                        "title": job.get("title", ""),
                        "company": job.get("company", ""),
                        "salary": job.get("salary", ""),
                        "location": job.get("location", ""),
                        "link": job.get("link", ""),
                    },
                    "analysis": analyze_one(job, resume),
                }
            )
            # 每条做完就重写整个文件：中断时已完成的结果留在盘上，
            # 重跑不用把已经付过钱的调用再来一遍。
            f.seek(0)
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.truncate()
            print(
                f"  [{i}/{len(jobs)}] {job['company']} · {job['title']} · "
                f"{time.perf_counter() - t0:.1f}s",
                flush=True,
            )
            import pdb; pdb.set_trace()  # noqa: T100


if __name__ == "__main__":
    main()
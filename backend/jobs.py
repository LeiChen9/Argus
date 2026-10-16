"""Jobs 领域：搜索结果持久化与查询。

单文件 data/boss_jobs.json（已 gitignore）：jobs 按 id 去重合并、新批次覆盖旧值，
batches 追加记录每次采集的关键词、来源与意向快照。

HTTP 层不在这里：Worker 侧只读 API 在 api_read.py（入口路由表在
entrypoint_worker.py），本模块只留领域函数。job_gaps 已退役，相关读取不再提供。
"""

import json
import os
import time
from pathlib import Path

from persona import TARGET_KEYS, get_persona
from utils import load_file, save_file

# 离线管线服务于单个账号：产物落 data/<用户>/，与 R2 上的命名空间一致。
# 默认 lbb；给别的账号跑离线脚本就 ARGUS_USER=xxx python3 …（Worker 侧由 cookie 决定）。
USER = os.environ.get("ARGUS_USER", "lbb")

STORE = Path(__file__).resolve().parents[1] / "data" / USER / "boss_jobs.json"
GAPS = Path(__file__).resolve().parents[1] / "data" / USER / "job_gaps.json"
CAREERS = Path(__file__).resolve().parents[1] / "data" / USER / "careers.json"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _load() -> dict:
    """读快照。Worker 模式 load_file 命中 store，离线读本地文件。"""
    return load_file(STORE) or {"updated_at": "", "batches": [], "jobs": {}}


def normalize(raw: dict, source: str) -> dict:
    return {
        "id": raw.get("encrypt_job_id") or raw.get("link") or raw["title"],
        "title": raw["title"],
        "company": raw.get("company") or raw.get("boss_name") or "",
        "salary": raw.get("salary", ""),
        "location": raw.get("location", ""),
        "tags": raw.get("tags", ""),
        "link": raw.get("link") or raw.get("job_link") or "",
        "source": source,
        "collected_at": _now(),
        "jd": raw.get("jd", ""),
        "skill_tags": raw.get("skill_tags", []),
        "boss_active_status": raw.get("boss_active_status", ""),
        # 下面这些 map_api_job 一直在返回，只是此前没存，详情页用得上
        "boss_title": raw.get("boss_title", ""),
        "company_scale": raw.get("company_scale", ""),
        "company_stage": raw.get("company_stage", ""),
        "company_industry": raw.get("company_industry", ""),
        "job_labels": raw.get("job_labels", ""),
        "skills": raw.get("skills", ""),
        "welfare": raw.get("welfare", ""),
        "company_link": raw.get("company_link", ""),
    }


def save_snapshot(cards: list[dict], keyword: str) -> None:
    filtered = [c for c in cards if c.get("jd")]
    persona = get_persona()
    store = {
        "updated_at": _now(),
        "batches": [{"keyword": keyword, "source": filtered[0]["source"] if filtered else "", "count": len(filtered), "persona_target": {k: persona.get(k) for k in TARGET_KEYS}, "at": _now()}],
        "jobs": {c["id"]: c for c in filtered},
    }
    STORE.parent.mkdir(exist_ok=True)
    save_file(STORE, store)


def job_cards() -> dict:
    """Jobs 页数据：updated_at + 全部岗位卡片。"""
    store = _load()
    return {"updated_at": store["updated_at"], "jobs": list(store["jobs"].values())}


def career_documents() -> dict:
    """Career 页数据：careers.json 逐成员回填 boss_jobs 的完整岗位。

    成员只有 job_id/company/title，缺 salary 与 location，画不出卡片：按 id 回填，
    页面拿到即可渲染。快照里消失的成员回落到 Career 内的 company/title 与
    belongs_note，不报错——Career 定义是人可编辑的地基，不该被快照漂移带着走。
    """
    doc = load_file(CAREERS)
    if not doc:
        return {"careers": []}
    jobs = _load()["jobs"]
    return {
        **doc,
        "careers": [
            {**f, "jobs": [{**j, **jobs.get(j["job_id"], {}), "id": j["job_id"]}
                           for j in f.get("jobs", [])]}
            for f in doc.get("careers", [])
        ],
    }


def gaps_by_job() -> dict:
    """{job_id: {"generated_at", "model", "analysis"}}

    data/job_gaps.json 的归一化视图。job_gaps 已退役：离线脚本 cluster_jobs.py 停用，
    Worker 侧不再提供它的读取入口。函数留着，重启这条线时不用重写。
    """
    if not GAPS.exists():
        return {}
    doc = json.loads(GAPS.read_text(encoding="utf-8"))
    at = doc.get("generated_at", "")
    # 带上跑这一批时的求职意向：intent_match 只说 aligned/above_target，
    # 没有目标值就说不出"对齐到什么"，前端得自己知道 25k-30k / 上海 才对得上。
    persona = doc.get("persona", {})
    target = {
        "target_base": persona.get("target_base", ""),
        "target_salary": persona.get("target_salary", ""),
        "target": persona.get("target", []),
    }
    return {
        r["job"]["id"]: {
            "generated_at": at,
            "model": r.get("model", ""),
            "analysis": r.get("analysis", {}),
            "target": target,
        }
        for r in doc.get("results", [])
    }

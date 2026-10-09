"""Jobs 领域：搜索结果持久化与查询。

单文件 data/jobs.json（已 gitignore）：jobs 按 id 去重合并、新批次覆盖旧值，
batches 追加记录每次采集的关键词、来源与意向快照。
"""

import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from common import save_json_file
from persona import TARGET_KEYS, get_persona

router = APIRouter()

STORE = Path(__file__).resolve().parents[1] / "data" / "boss_jobs.json"
GAPS = Path(__file__).resolve().parents[1] / "data" / "job_gaps.json"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _load() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {"updated_at": "", "batches": [], "jobs": {}}


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
    save_json_file(STORE, json.dumps(store, ensure_ascii=False, indent=2))


def _gaps() -> dict:
    """{job_id: {"generated_at", "model", "analysis"}}"""
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


@router.get("/api/jobs")
def list_jobs() -> dict:
    store = _load()
    return {"updated_at": store["updated_at"], "jobs": list(store["jobs"].values())}


@router.get("/api/jobs/{job_id}/analysis")
def job_analysis(job_id: str) -> dict:
    """单个岗位的 cluster 解读。analysis 原样透传，不在这里补字段：
    这一批 LLM 输出的键并不齐（openning/opening、defensive_script 三种变体、
    部分 gap_details 只有 has_gap），归一化放前端读时兜底，重跑就能自愈。"""
    row = _gaps().get(job_id)
    if not row:
        raise HTTPException(404, "该岗位暂无 AI 解读")
    return {"job_id": job_id, **row}

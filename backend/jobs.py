"""Jobs 领域：搜索结果持久化与查询。

单文件 data/jobs.json（已 gitignore）：jobs 按 id 去重合并、新批次覆盖旧值，
batches 追加记录每次采集的关键词、来源与意向快照。
"""

import json
import time
from pathlib import Path

from fastapi import APIRouter

from common import save_json_file
from persona import TARGET_KEYS, get_persona

router = APIRouter()

STORE = Path(__file__).resolve().parents[1] / "data" / "boss_jobs.json"


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


def save_batch(cards: list[dict], keyword: str) -> None:
    return save_snapshot(cards, keyword)


@router.get("/api/jobs")
def list_jobs() -> dict:
    store = _load()
    return {"updated_at": store["updated_at"], "jobs": list(store["jobs"].values())}

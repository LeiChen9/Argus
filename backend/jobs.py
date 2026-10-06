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

STORE = Path(__file__).resolve().parents[1] / "data" / "jobs.json"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _load() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {"updated_at": "", "batches": [], "jobs": {}}


def normalize(raw: dict, source: str) -> dict:
    """猎聘与 BOSS 两种返回结构归一为卡片模型。"""
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
    }


def save_batch(cards: list[dict], keyword: str) -> None:
    """按 id 合并去重（新覆盖旧），批次元数据追加，落盘。"""
    store = _load()
    store["jobs"] |= {c["id"]: c for c in cards}
    persona = get_persona()
    store["batches"].append({
        "keyword": keyword,
        "source": cards[0]["source"],
        "count": len(cards),
        "persona_target": {k: persona.get(k) for k in TARGET_KEYS},
        "at": _now(),
    })
    store["updated_at"] = _now()
    STORE.parent.mkdir(exist_ok=True)
    save_json_file(STORE, json.dumps(store, ensure_ascii=False, indent=2))


@router.get("/api/jobs")
def list_jobs() -> dict:
    store = _load()
    return {"updated_at": store["updated_at"], "jobs": list(store["jobs"].values())}

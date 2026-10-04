"""Jobs 领域：求职意向下的活跃岗位聚类。占位，爬虫未接。"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/jobs")
def jobs() -> dict:
    return {"jobs": [], "note": "placeholder，爬虫未接"}
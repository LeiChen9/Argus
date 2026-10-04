"""Me 领域：个人资料与设置。占位。"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/me")
def me() -> dict:
    return {"me": {}, "note": "placeholder"}
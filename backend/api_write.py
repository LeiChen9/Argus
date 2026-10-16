"""Worker 侧写路径：persona 上传 / 求职意向、简历手改。

领域逻辑全在 persona.py / resume.py（async + save_file_async，R2 与离线
双模式）；这里只做 HTTP 边界：multipart 解析、错误码映射（400 校验 /
404 没有 / 502 LLM 挂）。读路径在 api_read.py。

"""

from workers import Response

import resume
from persona import init_persona_from_text, read_upload, save_targets

VALID_OPS = {"set", "add", "remove", "move"}


class Bad(Exception):
    """HTTP 边界错误。entrypoint 接住转 JSON 响应。"""

    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


async def persona_init(request) -> Response:
    """POST /api/persona/init：传简历 md/txt，LLM 抽成 persona 落 R2。"""
    try:
        form = await request.form_data()
        f = form.get("file")
        if f is None:
            raise Bad("没有 file 字段")
        text = read_upload(f.name, await f.bytes())
    except ValueError as e:
        raise Bad(str(e))
    try:
        return Response.json(await init_persona_from_text(text))
    except Exception as e:
        # LLM 全链挂掉或 JSON 修不回来：与从前 FastAPI 版的 502 口径一致。
        return Response.json({"detail": f"LLM 解析失败：{e}"}, status=502)


async def persona_targets(request) -> Response:
    """PATCH /api/persona/targets：只改求职意向三个字段。"""
    body = await request.json()
    return Response.json(await save_targets(
        body.get("target") or [],
        body.get("target_base") or "",
        body.get("target_salary") or "",
    ))


async def resume_edits(career_id: str, request) -> Response:
    """POST /api/resumes/{id}/edits：用户在 Resume 页的手改，ops 照单落盘。"""
    body = await request.json()
    ops = body.get("ops") or []
    if any(op.get("op") not in VALID_OPS or not op.get("path") for op in ops):
        raise Bad("ops 只能是 set/add/remove/move 且必须带 path")
    try:
        return Response.json(await resume.apply_edits(
            career_id, ops, body.get("reason") or "手动编辑"))
    except FileNotFoundError as e:
        return Response.json({"detail": str(e)}, status=404)
    except ValueError as e:
        return Response.json({"detail": str(e)}, status=400)

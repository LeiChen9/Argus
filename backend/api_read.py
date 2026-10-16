"""Worker 侧只读 API：领域函数 → HTTP 响应的一层薄包装。

数据已由 entrypoint_worker._refresh 灌进 utils 的 store（每数据请求前 R2
全量拉取），这里只管取出来拼 Response——读哪份、怎么拼全是领域模块的事
（jobs.job_cards / resume.list_resumes / persona.get_persona），本文件不含
业务判断。写路径（persona 上传、简历编辑、chat 会话）不在这里，见后续切片。
"""

from workers import Response

import json
import jobs
import persona
import resume


def _json(payload, status: int = 200):
    return Response.json(payload, status=status)


def jobs_list():
    return _json(jobs.job_cards())


def careers_list():
    return _json(jobs.career_documents())


def resumes_list():
    return _json({"resumes": resume.list_resumes()})


async def resumes_list_ensured():
    """GET /api/resumes 的实际语义：先补齐每个 Career 的底稿再列（与从前
    FastAPI 版的 ensure_all 一致）。Worker 侧底稿也落 R2，零 LLM。"""
    return _json({"resumes": await resume.ensure_all()})


def resumes_get(career_id: str):
    doc = resume.document(career_id)
    if not doc:
        return _json({"detail": f"{career_id} 还没有简历"}, status=404)
    return _json(doc)


def persona_get():
    return _json(persona.get_persona())


async def me(user: str):
    """Me 页的数据：我是谁 + 我这个账号烧了多少 token（按模型分）。

    usage.json 由 Worker 在每轮对话结束时累加（见 entrypoint._merge_usage），
    这里只读。`_at` 是最后记账的时间戳，前端顺手显示「截至」。

    store 那一组是排障用的：careers/jobs/resumes 读的是 utils 的 store（每请求
    由 entrypoint._refresh 灌），而 /api/me 自己不读 store。症状是「me 正常、
    三个数据接口全空」时，只有把 store 的实际 key 打出来才知道断在哪一步——
    是没灌进去，还是灌进去的 key 和 load_file 要找的 key 对不上。
    """
    import utils
    from workers import env as workers_env

    try:
        obj = await workers_env.DATA.get(utils.user_prefix() + "usage.json")
        usage = json.loads(await obj.text()) if obj is not None else {}
    except Exception:
        usage = {}
    import jobs
    import resume
    return _json({"me": {"user": user},
                  "usage": {k: v for k, v in usage.items() if not k.startswith("_")},
                  "usage_at": usage.get("_at"),
                  "store_keys": sorted(utils.store_keys()),
                  "prefix": utils.user_prefix(),
                  "want_careers": utils.store_key(jobs.CAREERS),
                  "want_resumes": utils.store_key(resume.RESUME_DIR / "C1.json")})

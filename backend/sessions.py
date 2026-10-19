"""会话存取。线上唯一路径是 R2（chat_sessions/{sid}.json）。

**不是双实现择优**：离线脚本不碰 chat，session 只有 Worker 一个消费者。
内存字典只是测试与未注入 binding 时的兜底——Worker 启动即 bind_r2，
线上永远走不到兜底那条路。

隔离级内存的问题（C2a 实测）：免费档请求散在多个边缘节点，每个节点一个
isolate、各存一份会话——history 恢复十条里九条落空。落 R2 后读写都过同
一个 bucket，isolate 回收也不再丢历史。

**没有 TTL**：会话是用户看得见、自己能删的东西，就该一直在。从前 7 天懒删
是因为只有单一会话、没有 prune 手段；现在侧栏给了显式的删除入口，静默过期
反而成了数据丢失。单用户场景，同 sid 并发读改写竞争理论上存在、实际不可达——
真出问题那天再上 R2 的条件写（etag）。
"""

import json
import time

import utils

_env = None
_mem: dict[str, dict] = {}


def bind_r2(env) -> None:
    """entrypoint 加载时注入。调用前所有读写落内存（测试路径）。"""
    global _env
    _env = env


def backend_name() -> str:
    """当前后端。诊断用：chat 响应里带出来，线上不用翻日志。"""
    return "r2" if _env is not None else "memory"


def fresh() -> dict:
    return {"history": [], "resume_career": None, "updated_at": time.time()}


def _key(sid: str) -> str:
    """会话 key 也归到用户命名空间下：别人的 sid 猜到了也读不到。"""
    return f"{utils.user_prefix()}chat_sessions/{sid}.json"


async def load(sid: str) -> dict:
    if _env is None:
        return _mem.get(sid) or fresh()
    obj = await _env.DATA.get(_key(sid))
    if obj is None:
        return fresh()
    try:
        s = json.loads(await obj.text())
    except Exception:
        # 读坏了当没有：这一轮对话从头开始，好过让用户对着 500。
        return fresh()
    return s


def _summarize(sid: str, sess: dict) -> dict:
    """会话 → 侧栏行。标题优先取落盘的 title（首轮由 groq 起）；没有就退
    到首条用户消息截断，连用户消息都没有的空会话叫「新对话」。"""
    title = (sess.get("title") or "").strip()
    if not title:
        first = next((m["content"] for m in sess.get("history", []) if m["role"] == "user"), "")
        title = first.strip()[:20] or "新对话"
    return {"sid": sid, "title": title, "updated_at": sess.get("updated_at", 0)}


async def list_all() -> list[dict]:
    """当前用户的全部会话摘要，按更新时间倒序。Worker 列 R2 前缀下所有对象
    再逐个读（单个几 KB，量小）；内存兜底遍历字典。"""
    if _env is None:
        items = [_summarize(sid, s) for sid, s in _mem.items()]
    else:
        from pyodide.ffi import to_js
        prefix = f"{utils.user_prefix()}chat_sessions/"
        listed = await _env.DATA.list(to_js({"prefix": prefix}))
        items = []
        for obj in listed.objects:
            text = await (await _env.DATA.get(obj.key)).text()
            try:
                sess = json.loads(text)
            except Exception:
                continue
            items.append(_summarize(obj.key[len(prefix):-len(".json")], sess))
    return sorted(items, key=lambda x: x["updated_at"], reverse=True)


async def delete(sid: str) -> None:
    if _env is None:
        _mem.pop(sid, None)
        return
    await _env.DATA.delete(_key(sid))


async def save(sid: str, sess: dict) -> None:
    sess["updated_at"] = time.time()
    if _env is None:
        _mem[sid] = sess
        return
    await _env.DATA.put(
        _key(sid),
        json.dumps(sess, ensure_ascii=False, indent=2) + "\n",
    )

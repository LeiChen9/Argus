"""通用组件：认不得任何领域词汇的那一层。

只有三样东西放这里，因为它们确实跨领域、也确实省事：

- load_file / save_file：JSON 落盘
- apply_patch：对任意 JSON 文档打 patch，全成功才落
- tool：工具函数的公共外壳，把领域抛的异常收成 status/detail

**除此之外的一切都该留在领域文件里。** 一个领域需要自己的读取方式，就在那里写，
不要在这里开一个带领域前缀的函数——那只是把两行代码换个地方藏起来。
"""

from __future__ import annotations

import inspect
import json
from functools import wraps
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DATA = _HERE.parent / "data"


# ── R2 只读缓存（Worker 模式）────────────────────────────────────────────
#
# Worker 没有文件系统：entrypoint_worker._refresh 每个数据请求前从 R2 并行拉
# 全量文本灌进这里，load_file 优先查缓存，未命中退回本地文件。离线脚本从不
# 灌缓存，逐字节走老路。
#
# 缓存的是 text 不是 dict：领域函数照旧自己 json.loads，读哪份、读几次仍是
# 领域自己的事，缓存层不插足。（解析亚毫秒，已实测。）
_store: dict[str, str] = {}


def bind_store(texts: dict[str, str]) -> None:
    """整罐替换 store。Worker 每请求刷新时调；离线模式不调用。"""
    _store.clear()
    _store.update(texts)


def put_store(key: str, text: str) -> None:
    """写后把内容同步进 store：同请求内的后续读取要看得见刚写的东西。

    ensure_all 建档后当场列列表就靠这个——store 是请求开始时灌的快照，
    不补这一笔，刚建的底稿在本请求里不存在。
    """
    _store[key] = text


def store_active() -> bool:
    """是否 Worker 模式（store 被灌过）。领域模块据此切换双模式行为，
    典型是 persona 的单例：Worker 的 isolate 跨请求复用，单例会吐旧数据。"""
    return bool(_store)


def list_store_keys(prefix: str) -> list[str]:
    """store 里某前缀下的 key 列表——Worker 侧替代 glob（没有目录可扫）。"""
    return [k for k in _store if k.startswith(prefix)]


def _store_key(path: Path) -> str | None:
    """本地路径 → R2 key。data/ 下的路径原样映射（persona.json 也在 data/）。
    其余路径（报告、临时文件）不归 R2 管，永远走本地。"""
    p = Path(path).resolve()
    if p.is_relative_to(_DATA):
        return p.relative_to(_DATA).as_posix()
    return None


# ── 写通道（Worker 模式）───────────────────────────────────────────────
#
# save_file 是同步的（离线脚本直接调），Worker 写 R2 必须 await。领域侧凡是
# 落盘的函数统一改 async + await save_file_async；离线路径 _writer 未注入，
# 原地退回 save_file，行为不变。
_writer = None


def bind_writer(writer) -> None:
    """entrypoint 注入：async fn(key, text) -> None。注入后 save_file_async 走 R2。"""
    global _writer
    _writer = writer


async def save_file_async(path: Path, payload: dict) -> dict:
    """领域写入口。Worker 落 R2，离线落本地文件。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if _writer is not None:
        key = _store_key(path)
        if key is None:
            raise RuntimeError(f"R2 没有 {path} 对应的 key（只认 data/ 与 persona.json）")
        await _writer(key, text)
        put_store(key, text)
        return payload
    return save_file(path, payload)


def load_file(path: Path) -> dict | None:
    key = _store_key(path)
    if key is not None and key in _store:
        return json.loads(_store[key])
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_file(path: Path, payload: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload

# ── patch ────────────────────────────────────────────────────────────────
#
# 抄 Codex 的 apply_patch 与 Claude Code 的 Edit：改是改，不是重写。三条不变式——
#
# 1. **没点名的部分逐字节不变。** patch 里没有的路径，一个字符都不碰。
# 2. **全成功才落。** 任何一条落不了地，整份拒绝——半份 patch 比不 patch 糟得多。
# 3. **path 错了就报错。** 这两份 JSON 都是我们自己的代码生成的，格式固定、不会
#    越界不会撞车，所以不需要任何「防住外部脏数据」的检查。该拒绝的只有一种情况：
#    模型写错了 path。path 走不通时 Python 自己会抛（KeyError / IndexError /
#    TypeError），包上 ops[i] 的下标转成模型看得懂的话就够了。

def apply_patch(doc: dict, ops: list) -> tuple[dict, list[str]]:
    """按 ops 改 doc，返回 (新文档, 改了哪些 path)。任何一条落不了地就抛，doc 原封不动。

    path 是 JSON Pointer（RFC 6901），按文档结构走：列表段写下标，对象段写键名。
    `set` 改字段、`add` 往列表末尾追加（末段写 `-`）、`remove` 删掉、
    `move` 把末段下标那一项挪到 `to`（相邻两项对调就是 to = 末段 ± 1）。

      {"op": "set",    "path": "/work_history/0/projects/0/description", "value": "…"}
      {"op": "add",    "path": "/skills/-", "value": "SQL"}
      {"op": "remove", "path": "/work_history/0/projects/1"}
    """
    if not ops:
        return doc, []  # 空 ops 是「这轮什么都不改」，不是错误。第 3 条只拒绝 path 写错。
    out = json.loads(json.dumps(doc, ensure_ascii=False))  # 深拷贝，中途抛了原文档还在
    applied = []

    for i, op in enumerate(ops):
        kind, path = op["op"], op["path"]
        try:
            tokens = [t for t in path.split("/") if t]
            node = out
            for token in tokens[:-1]:
                node = node[int(token)] if isinstance(node, list) else node[token]
            last = tokens[-1]
            if kind == "add":
                node.append(op["value"])
            elif kind == "set":
                node[int(last) if isinstance(node, list) else last] = op["value"]
            elif kind == "move":
                node.insert(int(op["to"]), node.pop(int(last)))
            else:
                node.pop(int(last) if isinstance(node, list) else last)
        except Exception as e:
            # 路径走不通只有一种原因：模型写错了。Python 抛的 KeyError / IndexError
            # 本身够清楚，补上「第几条 ops、哪个 path」模型才知道自己错在哪。
            raise ValueError(f"ops[{i}] {kind} {path}: {e}") from e
        applied.append(f"{kind} {path}")

    return out, applied


# ── 工具外壳 ─────────────────────────────────────────────────────────────

def tool(fn):
    """工具函数的公共外壳：把领域抛的异常收成 {"status": "error"}。

    没有它的话，每个工具都得自己 try 一遍自己会抛的那几种异常；而 LLM 只认得 tool
    result 里的 status 字段——异常直接抛出去会变成 502，模型看不到「path 打错了」
    这句话，也就学不会下次打对。

    async 分支：调 LLM 的工具是协程函数，异常要到 await 时才抛，同步外壳接不住。
    """
    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def awrapped(*args, **kwargs) -> dict:
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                return {"status": "error", "detail": str(e)}
        return awrapped

    @wraps(fn)
    def wrapped(*args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return {"status": "error", "detail": str(e)}
    return wrapped
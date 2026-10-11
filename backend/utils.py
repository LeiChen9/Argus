"""通用组件：认不得任何领域词汇的那一层。

只有三样东西放这里，因为它们确实跨领域、也确实省事：

- load_file / save_file：JSON 落盘
- apply_patch：对任意 JSON 文档打 patch，全成功才落
- tool：工具函数的公共外壳，把领域抛的异常收成 status/detail

**除此之外的一切都该留在领域文件里。** 一个领域需要自己的读取方式，就在那里写，
不要在这里开一个带领域前缀的函数——那只是把两行代码换个地方藏起来。
"""

from __future__ import annotations

import json
from functools import wraps
from pathlib import Path


def load_file(path: Path) -> dict | None:
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
    `set` 改字段、`add` 往列表末尾追加（末段写 `-`）、`remove` 删掉。

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
    """
    @wraps(fn)
    def wrapped(*args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return {"status": "error", "detail": str(e)}
    return wrapped
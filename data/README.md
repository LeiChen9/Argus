# data/

入库与否：**只有本文件进 git，其余数据一律只落盘**。

本地 `data/` 不再是唯一副本——在线 Worker（Cloudflare Worker `argus-web`）读写的
是 R2 bucket `argus-data`。两边的关系：

| 对象 | 写方 | 同步 |
| --- | --- | --- |
| `boss_jobs.json` | 离线（crawler 快照，`backend/jobs.py::save_snapshot`，覆盖式） | 跑完 crawler 执行 `scripts/r2_push.sh` |
| `careers.json` | 离线（`scripts/build_careers.py`、`scripts/extract_capabilities.py`） | 同上 |
| `job_gaps.json` | 离线（`scripts/cluster_jobs.py`，legacy 已停用） | 不推，退役中 |
| `resumes/{career}.json` | **Web**（用户在 Resume 页手改，经 Worker 写 R2） | `scripts/r2_pull.sh` 拉回本地 |
| `persona.json` | **Web**（上传简历 / 改求职意向，经 Worker 写 R2） | 同上 |
| `chat_sessions/` | **Web**（chat 会话，Worker 写 R2） | 同上，本地只是留档 |
| `boss_jobs_*.json` / `careers_*.json` | 手工留档副本 | 不同步 |

`resumes/` 特殊：它是**用户自己的文件**，不是我们的派生物——用户亲手改过之后，
删掉就是删掉他的劳动，别当缓存清。

要更新数据就跑对应脚本，别用 Edit 改 JSON 内容。详见根目录 `AGENTS.md`。

# data/

入库与否：**只 `README.md` 进 git，其余数据一律只落盘**。

这里没有远端副本，删掉不可恢复。

| 文件 | 谁写 | 可否手改 |
| --- | --- | --- |
| `boss_jobs.json` | `backend/jobs.py::save_snapshot`，覆盖式快照 | 否 |
| `careers.json` | `scripts/build_careers.py`、`scripts/extract_capabilities.py` | 是，改前先问 |
| `job_gaps.json` | `scripts/cluster_jobs.py`，legacy | 否 |
| `boss_jobs_*.json` / `careers_*.json` | 手工留档副本 | 否 |

要更新数据就跑对应脚本，别用 Edit 改 JSON 内容。详见根目录 `AGENTS.md`。
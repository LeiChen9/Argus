# data/

入库与否：**只有本文件进 git，其余数据一律只落盘**。

本地 `data/` 不再是唯一副本——在线 Worker（Cloudflare Worker `argus-web`）读写的
是 R2 bucket `argus-data`。两边的关系：

| 对象 | 写方 | 同步 |
| --- | --- | --- |
| `users.json` | **人**（加账号就往里加一行，跑 `scripts/r2_push.sh` 推上去；Worker 只读不写账号） | `r2_push.sh` |
| `<用户>/boss_jobs.json` | 离线（crawler 快照，`backend/jobs.py::save_snapshot`，覆盖式） | 跑完 crawler 执行 `scripts/r2_push.sh` |
| `<用户>/careers.json` | 离线（`scripts/build_careers.py`、`scripts/extract_capabilities.py`） | 同上 |
| `<用户>/job_gaps.json` | 离线（`scripts/cluster_jobs.py`，legacy 已停用） | 不推，退役中 |
| `<用户>/resumes/{career}.json` | **Web**（用户在 Resume 页手改，经 Worker 写 R2） | `scripts/r2_pull.sh` 拉回本地 |
| `<用户>/persona.json` | **Web**（上传简历 / 改求职意向，经 Worker 写 R2） | 同上 |
| `<用户>/chat_sessions/` | **Web**（chat 会话，Worker 写 R2） | 同上，本地只是留档 |
| `<用户>/usage.json` | **Web**（每轮对话结束时 Worker 累加 token 用量，Me 页读它） | 不同步，账而已 |
| `boss_jobs_*.json` / `careers_*.json` | 手工留档副本（旧布局，未迁） | 不同步 |

## 目录即命名空间

每个账号一个子目录，**本机 `data/<用户>/` 和 R2 上 `<用户>/` 一一对应**——同名同
结构，所以同步就是 rclone copy，不用做路径映射。目前是 `data/lbb/`（2026-10-16
由扁平布局迁过来；R2 里旧路径留了一份 `_backup_pre_user_prefix/`）。

- `boss_jobs.json` / `careers.json` 是**共享资产**（岗位侧数据，不含个人信息）。
  新账号注册时 Worker 自动从种子账号 `lbb` 拷一份过去，否则新用户进来一片空白。
- `resumes/` 和 `persona.json` **绝不拷**：那是用户自己的东西。
- 离线脚本服务单个账号，默认 `lbb`；给别的账号跑就 `ARGUS_USER=xxx python3 …`，
  同步脚本则 `USER=xxx bash scripts/r2_pull.sh`。

`resumes/` 特殊：它是**用户自己的文件**，不是我们的派生物——用户亲手改过之后，
删掉就是删掉他的劳动，别当缓存清。

`users.json` 里是**明文密码**（用户明确要求，5 人私有工具，不上哈希）。它不经任何
API 回吐，R2 bucket 必须保持私有。

要更新数据就跑对应脚本，别用 Edit 改 JSON 内容。详见根目录 `AGENTS.md`。
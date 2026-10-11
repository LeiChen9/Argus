# Argus 工作规则

## data/ 是事实源，不是缓存

- `data/` 在 `.gitignore` 里，**不代表可丢弃**：它是本地唯一副本，没有远端备份。
- 默认**只读**。写入只能由 `data/README.md` 表里指定的脚本产生。
- 禁止把 `data/` 下任何文件当临时文件删改，包括 `rm data/*` 和用 Edit 直接改 JSON。
- `boss_jobs.json` / `job_gaps.json` 是覆盖式产物，手改即破坏快照。
- `careers.json` 人可编辑，但改动前先说明理由并等我同意。
- 需要重生成时，先告诉我会覆盖哪个文件、丢多少内容，得到同意再跑脚本。
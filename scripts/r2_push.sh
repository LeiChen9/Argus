#!/bin/bash
# scripts/r2_push.sh —— 离线管线的产物推上 R2，让线上 Worker 看见。
#
# 方向规则（与 r2_pull.sh 互为反面）：
#   careers.json boss_jobs.json  ← 离线脚本是写方：build_careers 聚类、
#                                  crawler 快照（跑完必须推，否则线上不更新）
#   resumes/ persona.json        ← 不推：Web 是写方，推上去会盖掉用户的手改
#   users.json                   ← 推：加新账号就在本机 data/users.json 里写一行再跑
#                                  一次这个脚本（人手写的，Worker 不提供增删账号）
#
# R2 上每个用户一个命名空间 <用户名>/，与本机 data/<用户名>/ 一一对应。
# 默认 lbb，推别人的产物就 USER=alice bash scripts/r2_push.sh
#
# 典型用法：python3 scripts/build_careers.py && bash scripts/r2_push.sh
set -euo pipefail

REMOTE="r2:argus-data"
USER="${USER:-lbb}"
cd "$(dirname "$0")/.."

rclone copyto --progress "data/$USER/careers.json" "$REMOTE/$USER/careers.json"
rclone copyto --progress "data/$USER/boss_jobs.json" "$REMOTE/$USER/boss_jobs.json"
[ -f data/users.json ] && rclone copyto --progress data/users.json "$REMOTE/users.json"

echo "推送完成：$USER/{careers.json, boss_jobs.json}（+ users.json）"
#!/bin/bash
# scripts/r2_push.sh —— 离线管线的产物推上 R2，让线上 Worker 看见。
#
# 方向规则（与 r2_pull.sh 互为反面）：
#   careers.json boss_jobs.json  ← 离线脚本是写方：build_careers 聚类、
#                                  crawler 快照（跑完必须推，否则线上不更新）
#   resumes/ persona.json        ← 不推：Web 是写方，推上去会盖掉用户的手改
#   users.json                   ← 不推：Web 注册会写 R2，本地旧副本推上去会
#                                  删掉新注册的账号
#
# R2 上每个用户一个命名空间 users/<用户名>/，与本机 data/<用户名>/ 一一对应。
# 默认 lbb，推别人的产物就 ARGUS_USER=alice bash scripts/r2_push.sh
#
# 典型用法：python3 scripts/build_careers.py && bash scripts/r2_push.sh
set -euo pipefail

REMOTE="r2:argus-data"
TARGET="${ARGUS_USER:-lbb}"
cd "$(dirname "$0")/.."

rclone copyto --progress "data/$TARGET/careers.json" "$REMOTE/users/$TARGET/careers.json"
rclone copyto --progress "data/$TARGET/boss_jobs.json" "$REMOTE/users/$TARGET/boss_jobs.json"

echo "推送完成：$TARGET/{careers.json, boss_jobs.json}"
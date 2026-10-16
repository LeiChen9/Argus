#!/bin/bash
# scripts/r2_push.sh —— 离线管线的产物推上 R2，让线上 Worker 看见。
#
# 方向规则（与 r2_pull.sh 互为反面）：
#   careers.json boss_jobs.json  ← 离线脚本是写方：build_careers 聚类、
#                                  crawler 快照（跑完必须推，否则线上不更新）
#   resumes/ persona.json        ← 不推：Web 是写方，推上去会盖掉用户的手改
#
# 典型用法：python3 scripts/build_careers.py && bash scripts/r2_push.sh
set -euo pipefail

REMOTE="r2:argus-data"
cd "$(dirname "$0")/.."

rclone copyto --progress data/careers.json "$REMOTE/careers.json"
rclone copyto --progress data/boss_jobs.json "$REMOTE/boss_jobs.json"

echo "推送完成：careers.json boss_jobs.json"

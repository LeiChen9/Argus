#!/bin/bash
# scripts/r2_pull.sh —— 把 Web 侧写的对象拉回本地 data/。
#
# 方向规则（与 r2_push.sh 互为反面，两头都写同一个键就是数据丢失）：
#   resumes/ persona.json chat_sessions/  ← Web 是写方：用户在 Resume 页手改、
#                                            chat 在 R2 攒会话、上传简历在建 persona
#   boss_jobs.json careers.json           ← 不拉：离线管线才是写方，见 r2_push.sh
#
# 什么时候跑：要用离线脚本（build_careers / cluster_jobs）之前先拉一次，
# 否则读到的是上周的简历。
set -euo pipefail

REMOTE="r2:argus-data"
cd "$(dirname "$0")/.."

rclone copy --progress "$REMOTE/resumes" data/resumes
rclone copyto --progress "$REMOTE/persona.json" data/persona.json
rclone copy --progress "$REMOTE/chat_sessions" data/chat_sessions

echo "拉取完成：resumes/ persona.json chat_sessions/"

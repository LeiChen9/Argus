#!/bin/bash
# scripts/r2_pull.sh —— 把 Web 侧写的对象拉回本地 data/<用户>/。
#
# 方向规则（与 r2_push.sh 互为反面，两头都写同一个键就是数据丢失）：
#   resumes/ persona.json chat_sessions/  ← Web 是写方：用户在 Resume 页手改、
#                                            chat 在 R2 攒会话、上传简历在建 persona
#   careers.json boss_jobs.json           ← 不拉：离线管线才是写方，见 r2_push.sh
#   users.json usage.json                 ← 不拉：users.json 本机就是编辑入口
#                                            （人可编辑，加人改这个文件再推），usage 是账
#
# R2 上每个用户一个命名空间 <用户名>/，本机同样：data/lbb/、data/alice/……
# 默认 lbb，给别人拉就 USER=alice bash scripts/r2_pull.sh
#
# 什么时候跑：要用离线脚本（build_careers / cluster_jobs）之前先拉一次，
# 否则读到的是上周的简历。
set -euo pipefail

REMOTE="r2:argus-data"
USER="${USER:-lbb}"
cd "$(dirname "$0")/.."

mkdir -p "data/$USER"
rclone copy --progress "$REMOTE/$USER/resumes" "data/$USER/resumes"
rclone copyto --progress "$REMOTE/$USER/persona.json" "data/$USER/persona.json"
rclone copy --progress "$REMOTE/$USER/chat_sessions" "data/$USER/chat_sessions"

echo "拉取完成：data/$USER/{resumes, persona.json, chat_sessions/}"
#!/bin/sh
# 公网入口看门狗：探端点，连续两次失败就调 restart.sh 换隧道。
#
# **不检测 DNS。** DNS 检测会漏掉真实故障：实测故障是 cloudflared 注册 quick tunnel
# 时 POST 超时、以及隧道建好后进程自己退出，两次 DNS 都是好的（api.trycloudflare.com
# 正常解析到 Cloudflare 段，手工 curl POST 每次都成功）。真正被污染的只有 workers.dev，
# 那影响的是本机直连公网入口，跟隧道存活是两回事。
#
# 探的是端点返不返 200，一个探测同时覆盖三种故障：注册失败、隧道掉线、进程被杀。
#
# 两个端点都要活：quick URL 活说明隧道在，公网入口活说明 Worker + KV 链路也通。
# 只探一个会漏——隧道活着但 KV 写坏，公网入口照样 530。
#
# 探测走 8118 代理（见 restart.sh 同理）：直连 trycloudflare 在本地网络下常超时，
# 用直连当判据会把好隧道误杀。
#
# 间隔与阈值：5 分钟一次、连续 2 次失败才动手。单次失败多半是抖动，而重启必然掉线，
# 误触发的代价是真断线。2 次失败 = 10 分钟内恢复，对自用工具够。
# 每 10 分钟最多调一次 restart.sh，撞不到 wrangler KV 写入的限流。
#
# 用法：
#   sh scripts/watchdog.sh &          # 前台起（Ctrl-C 停）
#   nohup sh scripts/watchdog.sh >/tmp/watchdog.log 2>&1 &   # 后台常驻
#   pkill -f watchdog.sh              # 停
ROOT=/Users/riceball/Documents/Projs/Argus
PXY=http://127.0.0.1:8118
ENTRY=https://argus-proxy.luent-hat.workers.dev
INTERVAL=300
THRESHOLD=2

ok() { curl -x $PXY -s -o /dev/null --max-time 15 "$1/api/jobs"; }

fail=0
while true; do
  sleep $INTERVAL

  # 没有隧道地址就没法探隧道，退化成只探公网入口。
  # 排除 api.：cloudflared 申请失败时打的 "Post \"https://api.trycloudflare.com/tunnel\""
  # 会被这个模式捞到，那是 API 地址不是隧道地址，探它必然"成功"——看门狗就永远健康。
  QUICK=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" /tmp/quick.log 2>/dev/null \
    | grep -v "^https://api\." | tail -1)

  if [ -n "$QUICK" ] && ok "$QUICK" && ok "$ENTRY"; then
    [ "$fail" -gt 0 ] && echo "$(date '+%m-%d %H:%M') 恢复了（连续失败 $fail 次）"
    fail=0
    continue
  fi

  fail=$((fail + 1))
  echo "$(date '+%m-%d %H:%M') 第 $fail 次失败（隧道 ${QUICK:-无}）"

  if [ "$fail" -ge "$THRESHOLD" ]; then
    echo "$(date '+%m-%d %H:%M') 连续 $fail 次失败，重启隧道"
    sh $ROOT/scripts/restart.sh 2>&1 | tail -3
    fail=0
  fi
done
#!/bin/sh
set -e
ROOT=/Users/riceball/Documents/Projs/Argus
PY=/Users/riceball/miniconda3/envs/echo/bin
PROXY=$ROOT/worker-proxy

pkill -f "cloudflared tunnel" 2>/dev/null; sleep 1
if ! lsof -i :7800 >/dev/null 2>&1; then
  nohup $PY/uvicorn main:app --app-dir $ROOT/backend --port 7800 --log-config $ROOT/uvicorn_config.json >/tmp/uvicorn_7800.log 2>&1 &
  sleep 2
fi

# quick tunnel 的地址是随机的。拿不到就整段放弃：继续往下走会把 Worker 的上游
# 洗成空值并推上线，公网入口直接瘫。宁可这次不更新。
# 排除 api.：cloudflared 失败时打的 "Post \"https://api.trycloudflare.com/tunnel\""
# 会被这个模式捞到，那是 API 地址不是隧道地址。
rm -f /tmp/quick.log
nohup cloudflared tunnel --url http://localhost:7800 >/tmp/quick.log 2>&1 &
QUICK=""
for i in 1 2 3 4 5 6; do
  sleep 4
  QUICK=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" /tmp/quick.log | grep -v "^https://api\." | tail -1)
  [ -n "$QUICK" ] && break
done
if [ -z "$QUICK" ]; then
  echo "tunnel 没起来，公网入口保持原样不动"; tail -3 /tmp/quick.log; exit 1
fi
echo "quick $QUICK"

# 部署前先确认 tunnel 真能通。DNS 生效比进程起来慢，实测要 10-20s。
# 走 8118 代理探测：直连 trycloudflare 在本地网络下常常超时，那是网络问题不是
# 隧道问题，用它做判据会把好隧道误杀。
UP=0
for i in 1 2 3 4 5 6 7 8; do
  if curl -x http://127.0.0.1:8118 -s -o /dev/null --max-time 15 "$QUICK/api/jobs"; then UP=1; break; fi
  sleep 3
done
if [ "$UP" != "1" ]; then
  echo "tunnel 起不来，公网入口保持原样不动"; exit 1
fi

# 上游写进 KV，不重新部署 Worker。上次换上游要 wrangler deploy，撞限流就失败，
# 而部署中途失败会把 ORIGIN 洗空并推上线；KV 写入失败则线上代码毫发无损。
npx --yes wrangler kv key put origin "$QUICK" --binding ORIGIN_KV --remote --cwd $PROXY >/dev/null

# KV 是最终一致的，刚写完立刻验可能读到旧值，重试。
for i in 1 2 3 4 5 6 7 8; do
  if curl -x http://127.0.0.1:8118 -s --max-time 15 https://argus-proxy.luent-hat.workers.dev/api/jobs \
    | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['jobs']; print(f\"verify {len(d['jobs'])} {d['updated_at']}\")"; then
    exit 0
  fi
  sleep 4
done
echo "公网校验没通过"; exit 1
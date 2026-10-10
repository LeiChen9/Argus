#!/bin/sh
set -e
ROOT=/Users/riceball/Documents/Projs/Argus
PY=/Users/riceball/miniconda3/envs/echo/bin
PROXY=$ROOT/worker-proxy

if ! lsof -i :7800 >/dev/null 2>&1; then
  nohup $PY/uvicorn main:app --app-dir $ROOT/backend --port 7800 --log-config $ROOT/uvicorn_config.json >/tmp/uvicorn_7800.log 2>&1 &
  sleep 2
fi

# 拿一个**真能通**的 quick tunnel 地址。重试 3 轮，因为申请 quick tunnel 会间歇性
# 超时（手工 POST 同样的请求每次都成功、耗时 4-5s，延迟偏高，cloudflared 偶尔错过
# 等待窗口）——这是随机失败不是配置问题，重试即可。
#
# 地址和探测必须合成一轮：**地址存在 ≠ 隧道存在**。cloudflared 注册失败时日志里照样
# 打得出 https://xxx.trycloudflare.com（那次是 Unauthorized: Tunnel not found），
# 只 grep 地址会把死隧道当好的，然后写进 KV，公网入口变成 530。
#
# 三轮都拿不到就整段放弃：继续往下走会把 Worker 的上游洗成空值并推上线，公网入口
# 直接瘫。宁可这次不更新。
# 排除 api.：cloudflared 失败时打的 "Post \"https://api.trycloudflare.com/tunnel\""
# 会被这个模式捞到，那是 API 地址不是隧道地址。
QUICK=""
for attempt in 1 2 3; do
  # || true：没有进程可杀时 pkill 返回 1，set -e 会直接干掉整个脚本。
  # 第二轮开始常常就是这样——上一轮的 cloudflared 已经自己退出了。
  pkill -f "cloudflared tunnel" 2>/dev/null || true
  sleep 1
  rm -f /tmp/quick.log
  nohup cloudflared tunnel --url http://localhost:7800 >/tmp/quick.log 2>&1 &

  URL=""
  for i in 1 2 3 4 5 6; do
    sleep 4
    URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" /tmp/quick.log | grep -v "^https://api\." | tail -1)
    [ -n "$URL" ] && break
  done

  # DNS 生效比进程起来慢，实测要 10-20s，所以这里要轮询而不是探一次。
  if [ -n "$URL" ]; then
    for i in 1 2 3 4 5 6 7 8; do
      if curl -x http://127.0.0.1:8118 -s -o /dev/null --max-time 15 "$URL/api/jobs"; then
        QUICK="$URL"; break
      fi
      sleep 3
    done
  fi

  [ -n "$QUICK" ] && break
  echo "第 $attempt 轮没拿到可用隧道，重试"
  tail -1 /tmp/quick.log
done
if [ -z "$QUICK" ]; then
  echo "tunnel 起不来，公网入口保持原样不动"; tail -3 /tmp/quick.log; exit 1
fi
echo "quick $QUICK"

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
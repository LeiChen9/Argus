#!/bin/sh
set -e
pkill -f "cloudflared tunnel" 2>/dev/null; sleep 1
if ! lsof -i :7800 >/dev/null 2>&1; then
  nohup /Users/riceball/miniconda3/envs/echo/bin/uvicorn main:app --app-dir /Users/riceball/Documents/Projs/Argus/backend --port 7800 --log-config /Users/riceball/Documents/Projs/Argus/uvicorn_config.json >/tmp/uvicorn_7800.log 2>&1 &
  sleep 2
fi
rm -f /tmp/quick.log
nohup cloudflared tunnel --url http://localhost:7800 >/tmp/quick.log 2>&1 &
sleep 6
QUICK=$(grep -o "https://[^ ]*trycloudflare.com" /tmp/quick.log | tail -1)
sed -i '' "s|https://.*trycloudflare.com|$QUICK|" /Users/riceball/Documents/Projs/Argus/worker-proxy/worker.js
npx --yes wrangler deploy --cwd /Users/riceball/Documents/Projs/Argus/worker-proxy >/tmp/wrangler.log 2>&1 &
W=$!
echo "quick $QUICK"
echo "fixed https://argus-proxy.luent-hat.workers.dev (updating...)"
wait $W
tail -n 5 /tmp/wrangler.log
curl -x http://127.0.0.1:8118 -s --max-time 10 https://argus-proxy.luent-hat.workers.dev/api/jobs | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"verify {len(d['jobs'])} {d['updated_at']}\")"

#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../vendor/boss-zhipin-scraper"
python3 -c "import requests, websocket" 2>/dev/null || {
  echo "缺少依赖：先 source activate echo（或 pip install -r vendor/boss-zhipin-scraper/requirements.txt）" >&2
  exit 1
}
python3 scripts/boss_cdp_raw.py --setup-chrome "$@"

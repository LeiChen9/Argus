#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export ARGUS_USER="${ARGUS_USER:-lbb}"
python3 scripts/crawl_jobs.py
bash scripts/r2_push.sh

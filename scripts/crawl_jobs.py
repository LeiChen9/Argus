"""采集 BOSS「为你推荐」岗位，写 data/<用户>/boss_jobs.json。

先在电脑上运行 scripts/setup_boss.sh 完成一次登录，再跑：
    ARGUS_USER=xxx python3 scripts/crawl_jobs.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

USER = os.environ.get("ARGUS_USER", "lbb")
os.environ["ARGUS_USER"] = USER

try:
    from crawler import fetch_boss_details, fetch_boss_recommendations
    from jobs import normalize, save_snapshot
except ImportError as e:
    print(f"采集依赖没装好：{e}", file=sys.stderr)
    print("先 source activate echo，或按 vendor/boss-zhipin-scraper/requirements.txt 安装依赖。", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    try:
        raws = fetch_boss_recommendations(max_batches=2, timeout=45)
    except Exception as e:
        print(f"BOSS 采集失败：{e}", file=sys.stderr)
        print("先在独立 Chrome 登录：bash scripts/setup_boss.sh", file=sys.stderr)
        raise SystemExit(1)

    if not raws:
        print("BOSS 推荐流没有返回岗位。确认已登录、账号有推荐岗位后重试。", file=sys.stderr)
        raise SystemExit(1)

    details = fetch_boss_details(raws)
    merged = []
    for j in raws:
        key = j.get("encrypt_job_id") or j.get("job_link") or j.get("title")
        d = details.get(key)
        if not d:
            continue
        j = {**j, "jd": d.get("jd", ""), "skill_tags": d.get("skill_tags", []),
             "boss_active_status": d.get("boss_active_status", "")}
        if j["jd"]:
            merged.append(j)

    if not merged:
        print("岗位详情没有拿到 JD，未写入快照。", file=sys.stderr)
        raise SystemExit(1)

    cards = [normalize(j, "boss_recommend") for j in merged]
    save_snapshot(cards, "BOSS推荐")
    print(f"采集 {len(cards)} 个岗位 → data/{USER}/boss_jobs.json")
    print(f"同步：ARGUS_USER={USER} bash scripts/r2_push.sh")


if __name__ == "__main__":
    main()

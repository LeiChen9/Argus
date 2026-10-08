import sys
import urllib.parse
from pathlib import Path

import httpx
import time
from common import SCRAPER_API_KEY, call_llm, clean_llm_json

BOSS_VENDOR_SCRIPTS = Path(__file__).resolve().parent.parent / "vendor" / "boss-zhipin-scraper" / "scripts"
BOSS_CDP_PORT = 9222


def fetch_boss_details(jobs: list[dict]) -> dict:
    if not jobs:
        return {}
    if str(BOSS_VENDOR_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(BOSS_VENDOR_SCRIPTS))
    import boss_cdp_raw as m

    adapted = [{**j, "job_id": j.get("encrypt_job_id") or j.get("job_link") or j.get("title")} for j in jobs]
    try:
        details = m.scrape_details({"jobs": adapted}, output_path="/tmp/boss_details_tmp.json")
    except Exception:
        return {}
    return {d["job_id"]: d for d in details if d.get("jd")}


def fetch_boss_recommendations(max_batches: int = 2, timeout: float = 45.0) -> list[dict]:
    """BOSS直聘首页“为你推荐”。CDP 旁听页面自身请求，需先运行 vendor 脚本 --setup-chrome 登录。"""
    if str(BOSS_VENDOR_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(BOSS_VENDOR_SCRIPTS))
    import boss_cdp_raw as m

    class _RecommendCapture(m.NetworkJoblistCapture):
        @staticmethod
        def _is_joblist_url(url):
            return "recommend/job/list" in url

    cdp = m.CDPSession(BOSS_CDP_PORT)
    tid, sid = m.create_page_session(cdp, background=True)
    cap = _RecommendCapture(cdp, sid)
    cap.enable()
    def scroll():
        import random
        for _ in range(random.randint(3, 5)):
            cdp.eval_js(f"window.scrollBy(0,{random.randint(200,600)})", sid)
            time.sleep(random.uniform(0.5, 1.5))
        cdp.eval_js("window.scrollTo(0, document.body.scrollHeight)", sid)
        time.sleep(random.uniform(1.5, 2.5))
    try:
        raws = []
        data = cap.wait_next_response(timeout, trigger=lambda: cdp.send("Page.navigate", {"url": "https://www.zhipin.com/"}, sid))
        if data:
            raws.append(data)
        deadline = time.time() + timeout
        while len(raws) < max_batches and time.time() < deadline:
            data = None
            for _ in range(3):
                data = cap.wait_next_response(min(10.0, deadline - time.time()), trigger=scroll)
                if data is not None:
                    break
            if data is None:
                break
            if data.get("zpData", {}).get("hasMore") is False:
                raws.append(data)
                break
            raws.append(data)
        jobs, seen = [], set()
        for d in raws:
            for j in m.map_api_jobs(d):
                key = j.get("encrypt_job_id")
                if key and key not in seen:
                    seen.add(key)
                    jobs.append(j)
        return jobs
    finally:
        try:
            cdp.send("Target.closeTarget", {"targetId": tid})
        finally:
            cdp.close()

CITY_DQS = {
    "上海": "020",
    "北京": "010",
    "广州": "050020",
    "深圳": "050090",
    "杭州": "070020",
    "成都": "090020",
    "南京": "060020",
    "苏州": "070030",
    "武汉": "180020",
    "西安": "200020",
}

def fetch_liepin_html(keyword: str) -> str:
    city = next((c for c in CITY_DQS if c in keyword), "")
    q = keyword.replace(city, "").strip() if city else keyword.strip()
    if not q:
        q = keyword.strip()
    url = f"https://www.liepin.com/zhaopin/?key={urllib.parse.quote(q)}"
    if city:
        url += f"&dqs={CITY_DQS[city]}"
    params = {"api_key": SCRAPER_API_KEY, "url": url, "render": "true", "premium": "true", "country_code": "cn"}
    with httpx.Client(timeout=90.0) as client:
        for attempt in range(3):
            resp = client.get("http://api.scraperapi.com/", params=params)
            if resp.status_code < 500:
                resp.raise_for_status()
                return resp.text
            if attempt == 2:
                resp.raise_for_status()
            time.sleep(2 ** attempt)
    raise RuntimeError("ScraperAPI 多次 5xx")

def parse_jobs(html: str) -> list[dict]:
    prompt = "分析以下猎聘 HTML，提取职位列表，字段固定为 title/company/salary/link。只输出 JSON 数组。"
    msg = call_llm([{"role": "user", "content": f"{prompt}\n\n{html[:80000]}"}], temperature=0.1)
    jobs = clean_llm_json(msg["content"] or "[]")
    out = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        out.append({"title": j.get("title") or j.get("job_title") or j.get("name") or "", "company": j.get("company") or "", "salary": j.get("salary") or "", "link": j.get("link") or j.get("url") or ""})
    return out

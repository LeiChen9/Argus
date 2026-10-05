import urllib.parse
import httpx
import time
from common import SCRAPER_API_KEY, call_llm, clean_llm_json

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

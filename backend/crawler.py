import json
import httpx
import time
from common import SCRAPER_API_KEY, call_llm, clean_llm_json

def fetch_boss_html(keyword: str) -> str:
    """用 ScraperAPI 绕过 Boss 直聘反爬，带指数退避重试。"""
    url = f"https://www.zhipin.com/web/geek/job?query={keyword}&city=101020100"
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": url,
        "render": "true",
        "premium": "true",
        "country_code": "cn",
    }
    with httpx.Client(timeout=60.0) as client:
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
    """LLM 读 HTML 抽职位 JSON，自动容灾。"""
    prompt = "分析以下 Boss 直聘 HTML，提取职位列表（职位名、公司、薪资、链接）。只输出 JSON 数组。"
    msg = call_llm([{"role": "user", "content": f"{prompt}\n\n{html[:80000]}"}], temperature=0.1)
    return clean_llm_json(msg["content"] or "[]")

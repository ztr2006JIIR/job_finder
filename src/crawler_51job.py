import json
import re
import gzip
import os
import sys
import time
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

import pandas as pd


PROJECT_DEPS = Path(__file__).resolve().parents[1] / ".deps"
if PROJECT_DEPS.exists() and str(PROJECT_DEPS) not in sys.path:
    sys.path.insert(0, str(PROJECT_DEPS))

PROJECT_BROWSERS = Path(__file__).resolve().parents[1] / ".browsers"
if PROJECT_BROWSERS.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PROJECT_BROWSERS))


CITY_CODES = {
    "全国": "000000",
    "北京": "010000",
    "上海": "020000",
    "广州": "030200",
    "深圳": "040000",
    "武汉": "180200",
    "西安": "200200",
    "杭州": "080200",
    "南京": "070200",
    "成都": "090200",
    "重庆": "060000",
    "苏州": "070300",
    "天津": "050000",
    "长沙": "190200",
    "郑州": "170200",
    "青岛": "120300",
}


OUTPUT_COLUMNS = ["title", "company", "city", "salary", "tags", "description", "source", "url"]


@dataclass
class CrawlResult:
    jobs: pd.DataFrame
    pages_fetched: int
    message: str = ""


class _JobLinkParser(HTMLParser):
    """轻量解析职位详情链接，作为页面 JSON 失效时的兜底方案。"""

    def __init__(self):
        super().__init__()
        self.links = []
        self._current_href = None
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href", "")
        if "jobs.51job.com" in href:
            self._current_href = href
            self._current_text = []

    def handle_data(self, data):
        if self._current_href:
            self._current_text.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "a" and self._current_href:
            title = " ".join(part for part in self._current_text if part)
            if title:
                self.links.append({"title": title, "url": self._current_href})
            self._current_href = None
            self._current_text = []


def crawl_51job(keyword, city="全国", pages=1, page_size=20, timeout=15, use_browser=True):
    """抓取前程无忧搜索结果，并整理为当前分析器可直接使用的 DataFrame。"""
    keyword = (keyword or "").strip()
    city = (city or "全国").strip()
    pages = max(1, int(pages or 1))
    page_size = max(1, int(page_size or 20))

    if not keyword:
        return CrawlResult(pd.DataFrame(columns=OUTPUT_COLUMNS), 0, "请输入岗位关键词。")

    all_jobs = []
    pages_fetched = 0
    message = ""
    for page in range(1, pages + 1):
        api_url = build_search_api_url(keyword, city, page, page_size)
        html = fetch_html(api_url, referer=build_pc_search_url(keyword, city), timeout=timeout)
        pages_fetched += 1
        if _is_waf_challenge(html):
            message = "接口请求触发了前程无忧访问防护，准备改用浏览器抓取。"
            break

        jobs = parse_search_payload(html)
        if not jobs:
            legacy_url = build_search_url(keyword, city, page)
            html = fetch_html(legacy_url, timeout=timeout)
            jobs = parse_search_page(html)

        all_jobs.extend(jobs)
        if len(all_jobs) >= pages * page_size:
            break
        if not jobs:
            break
        time.sleep(1)

    df = filter_jobs_by_city(normalize_jobs(all_jobs), city)
    if page_size:
        df = df.head(pages * page_size)
    if (df.empty or message) and use_browser:
        browser_result = crawl_51job_with_browser(keyword, city, pages, page_size, timeout=max(timeout, 30))
        if not browser_result.jobs.empty:
            return browser_result
        if browser_result.message:
            message = browser_result.message
    return CrawlResult(df, pages_fetched, message or f"已抓取 {len(df)} 条岗位。")


def build_search_api_url(keyword, city="全国", page=1, page_size=20):
    """生成前程无忧新版搜索接口地址。"""
    job_area = CITY_CODES.get(city, city if re.fullmatch(r"\d{6}", city or "") else "000000")
    params = {
        "api_key": "51job",
        "timestamp": str(int(time.time() * 1000)),
        "keyword": keyword,
        "searchType": "2",
        "function": "",
        "industry": "",
        "jobArea": job_area,
        "jobArea2": "",
        "landmark": "",
        "metro": "",
        "salary": "",
        "workYear": "",
        "degree": "",
        "companyType": "",
        "companySize": "",
        "jobType": "",
        "issueDate": "",
        "sortType": "0",
        "pageNum": str(page),
        "requestId": "",
        "pageSize": str(page_size),
        "source": "1",
        "accountId": "",
        "pageCode": "sou|sou|soulb",
    }
    return f"https://we.51job.com/api/job/search-pc?{urlencode(params)}"


def build_pc_search_url(keyword, city="全国", page=1):
    """生成浏览器搜索页地址，用作接口 Referer。"""
    job_area = CITY_CODES.get(city, city if re.fullmatch(r"\d{6}", city or "") else "000000")
    params = {
        "keyword": keyword,
        "searchType": "2",
        "sortType": "0",
        "metro": "",
        "jobArea": job_area,
        "pageNum": str(page),
    }
    return f"https://we.51job.com/pc/search?{urlencode(params)}"


def crawl_51job_with_browser(keyword, city="全国", pages=1, page_size=20, timeout=30, headless=True):
    """用真实浏览器加载前程无忧页面，并从接口响应或页面 DOM 中提取岗位。"""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return CrawlResult(
            pd.DataFrame(columns=OUTPUT_COLUMNS),
            0,
            "浏览器抓取需要安装 Playwright：pip install playwright && playwright install chromium",
        )

    all_jobs = []
    pages_fetched = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        )
        page_obj = context.new_page()

        for page in range(1, pages + 1):
            response_jobs = []

            def handle_response(response):
                if "search-pc" not in response.url:
                    return
                try:
                    response_jobs.extend(parse_search_payload(response.text()))
                except Exception:
                    return

            page_obj.on("response", handle_response)
            page_obj.goto(build_pc_search_url(keyword, city, page), wait_until="domcontentloaded", timeout=timeout * 1000)
            pages_fetched += 1
            try:
                page_obj.wait_for_load_state("networkidle", timeout=timeout * 1000)
            except PlaywrightTimeoutError:
                pass
            page_obj.wait_for_timeout(2000)

            jobs = response_jobs or _extract_jobs_from_browser_dom(page_obj)
            all_jobs.extend(jobs)
            page_obj.remove_listener("response", handle_response)
            if len(all_jobs) >= pages * page_size:
                break
            if not jobs:
                break

        context.close()
        browser.close()

    unfiltered_df = normalize_jobs(all_jobs)
    df = filter_jobs_by_city(unfiltered_df, city)
    if page_size:
        df = df.head(pages * page_size)
    if not df.empty:
        message = f"浏览器模式已抓取 {len(df)} 条岗位。"
    elif not unfiltered_df.empty and city != "全国":
        message = f"前程无忧返回了 {len(unfiltered_df)} 条岗位，但不属于 {city}，已过滤掉，可能是网站定位或访问防护导致城市失效。"
    else:
        message = "浏览器模式没有抓取到岗位，可能遇到登录、验证或页面结构变化。"
    return CrawlResult(df, pages_fetched, message)


def build_search_url(keyword, city="全国", page=1):
    """生成前程无忧搜索页地址。"""
    job_area = CITY_CODES.get(city, city if re.fullmatch(r"\d{6}", city or "") else "000000")
    encoded_keyword = quote(keyword.encode("gbk"))
    params = {
        "lang": "c",
        "stype": "",
        "postchannel": "0000",
        "workyear": "99",
        "cotype": "99",
        "degreefrom": "99",
        "jobterm": "99",
        "companysize": "99",
        "providesalary": "99",
        "lonlat": "0,0",
        "radius": "-1",
        "ord_field": "0",
        "confirmdate": "9",
        "fromType": "",
        "dibiaoid": "0",
        "address": "",
        "line": "",
        "specialarea": "00",
        "from": "",
        "welfare": "",
    }
    query = urlencode(params)
    return f"https://search.51job.com/list/{job_area},000000,0000,00,9,99,{encoded_keyword},2,{page}.html?{query}"


def fetch_html(url, referer=None, timeout=15):
    """下载搜索页 HTML。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(
        url,
        headers=headers,
    )
    with urlopen(request, timeout=timeout) as response:
        content = response.read()
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    return content.decode("utf-8", errors="replace")


def parse_search_payload(text):
    """解析前程无忧搜索接口响应。"""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _extract_jobs_from_json(payload)


def parse_search_page(html):
    """从搜索页提取职位列表。优先读内嵌 JSON，失败时退回链接解析。"""
    jobs = []
    for payload in _extract_json_payloads(html):
        jobs.extend(_extract_jobs_from_json(payload))
    if jobs:
        return jobs
    return _parse_links(html)


def _is_waf_challenge(text):
    waf_markers = ["aliyun_waf", "acw_sc__v2", "renderData", "arg1="]
    return any(marker in text for marker in waf_markers) and "jobId" not in text


def _extract_jobs_from_browser_dom(page_obj):
    """从浏览器已渲染页面中提取职位卡片。"""
    return page_obj.evaluate(
        """
        () => {
          const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
          const pickText = (root, selectors) => {
            for (const selector of selectors) {
              const node = root.querySelector(selector);
              const text = clean(node && node.innerText);
              if (text) return text;
            }
            return '';
          };
          const pickHref = (root) => {
            const links = Array.from(root.querySelectorAll('a[href]'));
            const jobLink = links.find((link) => /jobs\\.51job\\.com|we\\.51job\\.com\\/pc\\/job/.test(link.href));
            return jobLink ? jobLink.href : '';
          };
          const cards = Array.from(document.querySelectorAll(
            '.joblist-item, .j_joblist .e, .job_item, .job-card, [class*="joblist"] [class*="item"], [class*="job"]'
          ));
          const rows = [];
          const seen = new Set();
          for (const card of cards) {
            const href = pickHref(card);
            const text = clean(card.innerText);
            if (!href || !text || seen.has(href)) continue;
            seen.add(href);
            const title = pickText(card, ['.jname', '.job-name', '[class*="jobName"]', '[class*="title"]', 'a']);
            const company = pickText(card, ['.cname', '.company-name', '[class*="company"]']);
            const salary = pickText(card, ['.sal', '.salary', '[class*="salary"]']);
            const area = pickText(card, ['.area', '.location', '[class*="area"]', '[class*="location"]']);
            const tags = Array.from(card.querySelectorAll('.tags span, .tag, [class*="tag"] span'))
              .map((node) => clean(node.innerText))
              .filter(Boolean)
              .join(';');
            rows.push({
              title,
              company,
              city: area,
              salary,
              tags,
              description: text,
              url: href,
            });
          }
          return rows;
        }
        """
    )


def normalize_jobs(jobs):
    """把不同页面字段整理成分析器固定字段。"""
    rows = []
    seen = set()
    for job in jobs:
        row = _normalize_job(job)
        unique_key = (row["title"], row["company"], row["city"], row["url"])
        if not row["title"] or unique_key in seen:
            continue
        seen.add(unique_key)
        rows.append(row)
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def filter_jobs_by_city(df, city):
    """避免网站返回默认城市时，把错误城市的数据混进当前抓取结果。"""
    city = (city or "全国").strip()
    if df.empty or city == "全国" or "city" not in df.columns:
        return df
    return df[df["city"].fillna("").astype(str).str.startswith(city)].reset_index(drop=True)


def _extract_json_payloads(html):
    patterns = [
        r"__SEARCH_RESULT__\s*=\s*(\{.*?\})\s*</script>",
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>",
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    ]
    payloads = []
    for pattern in patterns:
        for match in re.finditer(pattern, html, flags=re.DOTALL | re.IGNORECASE):
            text = unescape(match.group(1)).strip().rstrip(";")
            try:
                payloads.append(json.loads(text))
            except json.JSONDecodeError:
                continue
    return payloads


def _extract_jobs_from_json(payload):
    if isinstance(payload, list):
        jobs = []
        for item in payload:
            jobs.extend(_extract_jobs_from_json(item))
        return jobs

    if not isinstance(payload, dict):
        return []

    jobs = []
    for key in ("engine_jds", "jobList", "job_list", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            jobs.extend(item for item in value if isinstance(item, dict))

    if _looks_like_job(payload):
        jobs.append(payload)

    for value in payload.values():
        if isinstance(value, (dict, list)):
            jobs.extend(_extract_jobs_from_json(value))
    return jobs


def _looks_like_job(payload):
    keys = set(payload)
    title_keys = {"job_name", "jobName", "job_title", "jobTitle", "title", "name"}
    company_keys = {"company_name", "companyName", "fullCompanyName", "company"}
    url_keys = {"job_href", "jobHref", "job_url", "jobUrl", "url"}
    return bool(keys & title_keys) and bool((keys & company_keys) or (keys & url_keys))


def _parse_links(html):
    parser = _JobLinkParser()
    parser.feed(html)
    return parser.links


def _normalize_job(job):
    title = _pick(job, "job_name", "jobName", "job_title", "jobTitle", "title", "name")
    company = _pick(job, "company_name", "companyName", "fullCompanyName", "company")
    salary = _pick(job, "providesalary_text", "provideSalaryString", "salary", "salaryString")
    city = _pick(job, "workarea_text", "jobAreaString", "jobArea", "city", "area")
    url = _pick(job, "job_href", "jobHref", "job_url", "jobUrl", "url")
    description = _pick(job, "jobDescribe", "job_description", "describe", "description", "jobInfo")
    tags = _join_values(
        _pick(job, "jobwelf", "welfare", "welfareText"),
        job.get("job_welf_list"),
        job.get("welfareList"),
        job.get("attribute_text"),
        job.get("attributeText"),
    )

    if isinstance(city, str) and "-" in city:
        city = city.split("-")[0]

    return {
        "title": _clean_text(title),
        "company": _clean_text(company),
        "city": _clean_text(city),
        "salary": _clean_text(salary) or "面议",
        "tags": _clean_text(tags),
        "description": _clean_text(description),
        "source": "前程无忧",
        "url": _clean_text(url),
    }


def _pick(mapping, *keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return ""


def _join_values(*values):
    parts = []
    for value in values:
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
        elif value:
            parts.append(str(value))
    return ";".join(parts)


def _clean_text(value):
    if isinstance(value, list):
        value = ";".join(str(item) for item in value if item)
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

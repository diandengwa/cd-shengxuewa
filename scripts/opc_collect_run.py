#!/usr/bin/env python3
"""
OPC 采集 Agent v4 - 2026-05-31
复用 kb_collect_articles.py 已验证的 ArticleCollector 来调 API
（它的 requests.Session() + X-Auth-Key 在服务器上能跑通）
"""

import os, json, time, re, argparse
from datetime import datetime, timedelta
from pathlib import Path

# ==========================================================
# 配置
# ==========================================================
BASE_DIR    = "/opt/k12-rocket/opc/collect"
RAW_DIR     = os.path.join(BASE_DIR, "raw-articles")
RETRY_LIST  = os.path.join(RAW_DIR, "_retry_urls.json")
LOG_DIR     = os.path.join(BASE_DIR, "logs")

# 高优先级账号（对标账号 + 官方账号）
HIGH_ACCOUNTS = [
    {"name": "乐儿爸sai话多", "fakeid": "Mzk0MDI5Mzc0OQ==", "priority": "high"},
    {"name": "祺爸说初升高",   "fakeid": "Mzg4NDE4OTI1Mw==", "priority": "high"},
    {"name": "成都教育发布",    "fakeid": "MzIzMjQ0MTIzOQ==", "priority": "high"},
    {"name": "锦江教育",        "fakeid": "MzAxMjU4NTk2OQ==", "priority": "high"},
    {"name": "成都高新区教育体育局", "fakeid": "Mzk0MTM5MTU3MA==", "priority": "high"},
]

# 时效过滤：只采集 N 天内的文章（可被 --days 覆盖）
FRESHNESS_DAYS = 60

# ==========================================================
# 复用 kb_collect_articles.py 的 ArticleCollector
# （它的 requests.Session() + X-Auth-Key 已验证能跑通）
# ==========================================================
import sys
sys.path.insert(0, "/opt/k12-rocket")
from kb_collect_articles import ArticleCollector

_collector = ArticleCollector()   # 复用已验证的 session


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name)[:80]


def is_too_old(pub_time_str, freshness_days):
    """检查文章是否太旧（超过 freshness_days 天）"""
    if not pub_time_str:
        return False
    try:
        pub_dt = datetime.fromtimestamp(int(pub_time_str[:10]))
        cutoff = datetime.now() - timedelta(days=freshness_days)
        return pub_dt < cutoff
    except Exception:
        return False


def call_api_list_articles(fakeid, limit=50):
    """获取文章列表（复用 ArticleCollector.session）"""
    url = "https://down.mptext.top/api/public/v1/articles"
    params = {"fakeid": fakeid, "limit": limit}
    try:
        resp = _collector.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("base_resp", {}).get("ret", 0) != 0:
            log(f"  API error: {data.get('base_resp', {})}")
            return None
        return data
    except Exception as e:
        log(f"  API list error: {e}")
        return None


def call_api_download(url):
    """下载文章内容（复用 ArticleCollector.download_article）"""
    return _collector.download_article(url)


# ==========================================================
# 主采集逻辑
# ==========================================================
def main():
    global FRESHNESS_DAYS
    parser = argparse.ArgumentParser(description="OPC 采集 Agent v4")
    parser.add_argument("--dry-run", action="store_true", help="仅打印待采集文章，不下载")
    parser.add_argument("--date", type=str, default=None, help="指定采集日期 YYYY-MM-DD（默认：今天）")
    parser.add_argument("--days", type=int, default=None, help=f"采集最近N天，覆盖默认值（默认：{FRESHNESS_DAYS}）")
    args = parser.parse_args()

    if args.days is not None:
        FRESHNESS_DAYS = args.days

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    log(f"=== OPC Collect v4 ===")
    log(f"RAW_DIR: {RAW_DIR}")
    log(f"FRESHNESS_DAYS: {FRESHNESS_DAYS}")
    log(f"High-priority accounts: {len(HIGH_ACCOUNTS)}")

    # 加载已有 URL 去重
    existing_urls = set()
    retry_urls = []
    if os.path.exists(RETRY_LIST):
        try:
            with open(RETRY_LIST, "r", encoding="utf-8") as f:
                retry_urls = json.load(f)
            log(f"Loaded {len(retry_urls)} retry URLs")
        except Exception:
            pass

    # 遍历高优先级账号
    total_new      = 0
    total_skipped  = 0
    total_filtered = 0
    total_errors   = 0
    account_results = []

    for acct in HIGH_ACCOUNTS:
        name    = acct["name"]
        fakeid  = acct["fakeid"]
        log(f"\n--- Account: {name} ---")

        # 1. 获取文章列表（复用 ArticleCollector 的 session）
        list_data = call_api_list_articles(fakeid, limit=50)
        if not list_data or not list_data.get("data"):
            log(f"  Failed to fetch article list")
            total_errors += 1
            account_results.append({"name": name, "new": 0, "skipped": 0, "filtered": 0, "error": True})
            continue

        articles = list_data["data"]
        log(f"  Fetched {len(articles)} articles")

        acct_new      = 0
        acct_skipped  = 0
        acct_filtered = 0

        for art in articles:
            art_url   = art.get("url", "")
            art_time  = str(art.get("update_time", ""))
            title     = art.get("title", "untitled")

            # 去重
            if art_url in existing_urls:
                acct_skipped += 1
                continue

            # 时效过滤
            if is_too_old(art_time, FRESHNESS_DAYS):
                acct_filtered += 1
                continue

            if args.dry_run:
                log(f"  [dry-run] Would download: {title}")
                continue

            # 2. 下载文章内容（复用 ArticleCollector.download_article）
            log(f"  Downloading: {title[:40]}...")
            md_content = call_api_download(art_url)
            if not md_content:
                log(f"    Download failed, will retry later")
                retry_urls.append(art_url)
                time.sleep(3)
                continue

            category = "policy" if any(kw in title for kw in ["政策", "通知", "公告", "办法"]) else "news"

            # 3. 保存为 MD（带 YAML front matter）
            acct_dir = os.path.join(RAW_DIR, sanitize_filename(name))
            os.makedirs(acct_dir, exist_ok=True)
            filename = sanitize_filename(title) + ".md"

            pub_time_str = datetime.fromtimestamp(int(art_time[:10])).strftime("%Y-%m-%d %H:%M:%S") if art_time else today_str()

            front_matter = (
                f"---\n"
                f'title: "{title.replace(chr(34), chr(92)+chr(34))}"\n'
                f"source: {name}\n"
                f"category: {category}\n"
                f"url: {art_url}\n"
                f"collected_at: {today_str()}\n"
                f'pub_time: "{pub_time_str}"\n'
                f"---\n\n"
            )

            filepath = os.path.join(acct_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(front_matter + md_content)

            existing_urls.add(art_url)
            acct_new += 1
            log(f"    SAVED: {filename} ({len(md_content)} chars)")
            time.sleep(2)

        total_new      += acct_new
        total_skipped  += acct_skipped
        total_filtered += acct_filtered
        account_results.append({
            "name": name, "new": acct_new, "skipped": acct_skipped,
            "filtered": acct_filtered, "error": False
        })
        log(f"  Account summary: {acct_new} new, {acct_skipped} skipped, {acct_filtered} filtered")

    # 保存 retry list
    with open(RETRY_LIST, "w", encoding="utf-8") as f:
        json.dump(retry_urls, f, ensure_ascii=False, indent=2)

    # 更新 pipeline-state.json
    state_path = os.path.join(BASE_DIR, "pipeline-state.json")
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        state["agents"]["opc-collect"] = {
            "status": "done",
            "last_run": today_str(),
            "new_articles": total_new,
            "skipped": total_skipped,
            "filtered": total_filtered,
            "errors": total_errors,
            "accounts_processed": len(account_results),
        }
        if total_new > 0:
            state["agents"]["opc-mine"]["status"] = "pending"
        state["updated_at"] = now_iso()
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    log("=== OPC Collect Complete ===")
    log(f"Total new articles: {total_new}")
    log(f"Total skipped (existing): {total_skipped}")
    log(f"Total filtered (too old): {total_filtered}")
    log(f"Total errors: {total_errors}")
    print(f"RESULT: {total_new} new articles collected, {total_filtered} filtered (too old)")


if __name__ == "__main__":
    main()

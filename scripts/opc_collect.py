#!/usr/bin/env python3
"""
OPC 竞争对手公众号文章采集脚本（支持断点续传 + 分页全量采集）
- 分页拉取：循环翻页，确保30天内所有文章（含多图文头条）全部被采集
- 三层过滤：标题黑名单、时间过滤、正文长度过滤
- 去重：基于 URL（跨天自动去重）
- 断点续传：记录已采集账号索引，跨天自动重置
- 异常捕获：单篇文章/单个账号出错不影响整体运行
- 全局异常捕获：任何未处理异常写入日志文件，不丢失进度
"""

import json, os, time, re, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote
from datetime import datetime, timedelta

API_BASE   = "https://down.mptext.top/api/public/v1"
AUTH_KEY   = "fb0dd96bc791414da86ade714bfc28fb"
RAW_DIR    = r"/app/raw-articles"
PIPELINE_FILE = r"/app/pipeline-state.json"
INDEX_FILE  = r"/app/knowledge-base/index.json"
RETRY_FILE  = r"/app/scripts/retry_list.json"
ACCOUNTS_FILE = r"/app/competitors/accounts.json"
PROGRESS_FILE = r"/app/pipeline-logs/collect-progress.json"

today     = datetime.now().strftime("%Y-%m-%d")
LOG_FILE  = r"/app/pipeline-logs/collect-{today}.log"

# === Filter Config ===
TITLE_WHITELIST_OFFICIAL = re.compile(r"招生简章|招生方案|招生计划|入学须知|报名指南")
TITLE_BLACKLIST_LOOSE = re.compile(r"(扫码加群|赶快来加入我们|会员招募|加入会员群)")
TITLE_BLACKLIST_STRICT = re.compile(
    r"(会员|加入群|体验营|报名启动|招募"
    r"|会员服务|赶快来加入|扫码加群|家长圈会员)"
)

MIN_BODY_LENGTH     = 500
MAX_ARTICLE_AGE_DAYS = 30
CUTOFF_TIMESTAMP = int((datetime.now() - timedelta(days=MAX_ARTICLE_AGE_DAYS)).timestamp())

# === Filter Functions ===
def is_title_blacklisted(title, category='自媒体号'):
    if category in {'官方政策号', '名校'}:
        if TITLE_WHITELIST_OFFICIAL.search(title):
            return False
        return bool(TITLE_BLACKLIST_LOOSE.search(title))
    else:
        return bool(TITLE_BLACKLIST_STRICT.search(title))

def is_too_old(update_time_ts):
    if not update_time_ts:
        return False
    return int(update_time_ts) < CUTOFF_TIMESTAMP

def is_body_too_short(md_content):
    cleaned = re.sub(r'!\[.*?\]\(.*?\)', '', md_content)
    cleaned = re.sub(r'\[.*?\]\(.*?\)', '', cleaned)
    cleaned = re.sub(r'[*_~`#>-]', '', cleaned)
    cleaned = re.sub(r'\s+', '', cleaned)
    return len(cleaned) < MIN_BODY_LENGTH

# === Helpers ===
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def api_get(path, retries=3, raw=False):
    url = f"{API_BASE}{path}"
    for attempt in range(retries):
        try:
            req = Request(url)
            req.add_header("X-Auth-Key", AUTH_KEY)
            req.add_header("User-Agent", "OPC-Collect/1.0")
            with urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                if raw:
                    return {"data": body}
                data = json.loads(body)
                if data.get("code") == 200013:
                    return {"error": "auth_expired", "code": 200013}
                return data
        except HTTPError as e:
            if e.code == 429:
                log(f"  Rate limited (429), waiting 60s... attempt {attempt+1}/{retries}")
                time.sleep(60)
                continue
            log(f"  HTTP error {e.code}: {e.reason}")
            return {"error": f"http_{e.code}"}
        except Exception as e:
            log(f"  Network error: {e}, attempt {attempt+1}/{retries}")
            if attempt < retries - 1:
                time.sleep(10)
            else:
                return {"error": str(e)}
    return {"error": "max_retries_exceeded"}

def sanitize_filename(title):
    title = re.sub(r'[\\/:*?"<>|\n\r\t]', '_', title)
    title = title.strip('. ')[:80]
    return title if title else "untitled"

def load_existing_urls():
    existing_urls = set()
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                index = json.load(f)
            for entry in index.get("articles_index", []):
                if "url" in entry:
                    existing_urls.add(entry["url"])
        except Exception:
            pass
    if os.path.exists(RAW_DIR):
        for prev_date_dir in os.listdir(RAW_DIR):
            prev_path = os.path.join(RAW_DIR, prev_date_dir)
            if not os.path.isdir(prev_path):
                continue
            for root, dirs, files in os.walk(prev_path):
                for fn in files:
                    if fn.endswith(".md"):
                        fpath = os.path.join(root, fn)
                        try:
                            with open(fpath, "r", encoding="utf-8") as f:
                                content = f.read(2048)
                            m = re.search(r'^url:\s*(.+)$', content, re.MULTILINE)
                            if m:
                                existing_urls.add(m.group(1).strip())
                        except Exception:
                            pass
    return existing_urls

def load_progress():
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                progress = json.load(f)
            if progress.get("date", "") != today_str:
                log(f"[progress] Previous day's progress found, clearing")
                try:
                    os.remove(PROGRESS_FILE)
                except Exception:
                    pass
                return {"last_completed_index": -1, "completed_accounts": [], "date": today_str}
            return progress
        except Exception:
            pass
    return {"last_completed_index": -1, "completed_accounts": [], "date": today_str}

def save_progress(index, account_name):
    try:
        progress = load_progress()
        progress["last_completed_index"] = index
        progress["date"] = today
        if account_name not in progress["completed_accounts"]:
            progress["completed_accounts"].append(account_name)
        os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"  Warning: failed to save progress: {e}")

def fetch_account_articles(fakeid, account_name):
    all_articles = []
    begin = 0
    batch_size = 50

    while True:
        result = api_get(f"/article?fakeid={fakeid}&begin={begin}&size={batch_size}")
        time.sleep(1)

        if "error" in result:
            log(f"  [pagination] ERROR at begin={begin}: {result['error']}")
            break

        articles = result.get("articles", [])
        if not articles:
            log(f"  [pagination] empty batch at begin={begin}, stopping")
            break

        batch_within = [a for a in articles if not is_too_old(a.get("update_time", 0))]
        batch_too_old = len(articles) - len(batch_within)

        all_articles.extend(batch_within)

        if batch_within:
            log(f"  [pagination] begin={begin}: {len(batch_within)}/{len(articles)} within window (total={len(all_articles)})")
        else:
            log(f"  [pagination] begin={begin}: all {len(articles)} articles too old")

        if batch_too_old == len(articles):
            log(f"  [pagination] all articles at begin={begin} are too old, stopping")
            break

        if len(articles) < batch_size:
            log(f"  [pagination] got {len(articles)} < {batch_size}, reached end")
            break

        begin += batch_size

    return all_articles

def process_article(article, name, category, acct_dir, existing_urls, retry_list):
    try:
        content_url = article.get("link", "")
        title       = article.get("title", "untitled")
        update_time = article.get("update_time", 0)

        if is_title_blacklisted(title, category):
            log(f"  SKIP (title_blacklist): {title[:40]}")
            return "skipped"

        if is_too_old(update_time):
            log(f"  SKIP (too old): {title[:40]}")
            return "skipped"

        if content_url in existing_urls:
            log(f"  SKIP (existing): {title[:40]}")
            return "skipped"

        if not content_url:
            log(f"  SKIP (no URL): {title[:40]}")
            return "skipped"

        log(f"  Downloading: {title[:50]}")
        dl_result = api_get(f"/download?url={quote(content_url, safe='')}&format=markdown", raw=True)
        time.sleep(2)

        if "error" in dl_result:
            log(f"  Download failed: {dl_result['error']}")
            retry_list.append({"url": content_url, "title": title, "account": name})
            return "retry"

        md_content = dl_result.get("data", "")

        if md_content and is_body_too_short(md_content):
            log(f"  SKIP (body too short): {title[:40]}")
            return "skipped"

        if md_content:
            os.makedirs(acct_dir, exist_ok=True)
            safe_title = sanitize_filename(title)
            filepath = os.path.join(acct_dir, f"{safe_title}.md")
            header = (
                f"---\n"
                f"source: {name}\n"
                f"url: {content_url}\n"
                f"collected: {datetime.now().isoformat()}\n"
                f"update_time: {update_time}\n"
                f"---\n\n"
            )
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(header + md_content)
            log(f"  SAVED: {safe_title}.md")
            existing_urls.add(content_url)
            return "saved"
        else:
            log(f"  Empty content for: {title[:40]}")
            retry_list.append({"url": content_url, "title": title, "account": name})
            return "retry"

    except Exception as e:
        log(f"  ERROR processing '{title[:30]}': {e}")
        return "error"

def main():
    os.makedirs(os.path.join(RAW_DIR, today), exist_ok=True)
    log(f"=== OPC Collect Agent Started (date={today}) ===")

    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        accounts = json.load(f)
    high_accounts = [a for a in accounts if a.get("priority") == "high"]
    log(f"Found {len(high_accounts)} high-priority accounts")

    progress = load_progress()
    start_index = progress["last_completed_index"] + 1
    if start_index > 0:
        log(f"Resuming from account {start_index+1}/{len(high_accounts)}")

    existing_urls = load_existing_urls()
    log(f"Loaded {len(existing_urls)} existing URLs for dedup")

    with open(PIPELINE_FILE, "r", encoding="utf-8") as f:
        pipeline = json.load(f)

    total_new          = 0
    total_filtered_title = 0
    total_filtered_age   = 0
    total_filtered_body  = 0
    account_results    = []
    error_log          = []
    retry_list          = []

    for i, account in enumerate(high_accounts):
        if i < start_index:
            log(f"[{i+1}/{len(high_accounts)}] SKIPPING (already completed): {account['name']}")
            continue

        name     = account["name"]
        fakeid   = account["fakeid"]
        category = account.get("category", "自媒体号")
        log(f"[{i+1}/{len(high_accounts)}] Fetching: {name} (category={category})")

        try:
            articles = fetch_account_articles(fakeid, name)
        except Exception as e:
            log(f"  ERROR fetching articles for {name}: {e}")
            error_log.append({"account": name, "error": str(e)})
            account_results.append({"name": name, "status": "error", "new_articles_count": 0})
            save_progress(i, name)
            continue

        if not articles:
            log(f"  No articles within 30 days for {name}")
            account_results.append({"name": name, "status": "empty", "new_articles_count": 0})
            save_progress(i, name)
            continue

        log(f"  Total articles within 30 days (after pagination): {len(articles)}")
        acct_dir = os.path.join(RAW_DIR, today, name)

        new_count    = 0
        filtered_title = 0
        filtered_age   = 0
        filtered_body  = 0

        for article in articles:
            result = process_article(article, name, category, acct_dir, existing_urls, retry_list)
            if result == "saved":
                new_count += 1
            elif result == "skipped":
                title = article.get("title", "")
                if is_title_blacklisted(title, category):
                    filtered_title += 1
                elif is_too_old(article.get("update_time", 0)):
                    filtered_age += 1
                elif article.get("link", "") in existing_urls:
                    pass
                else:
                    filtered_body += 1

        total_new           += new_count
        total_filtered_title += filtered_title
        total_filtered_age   += filtered_age
        total_filtered_body  += filtered_body

        account_results.append({
            "name": name,
            "status": "done",
            "new_articles_count": new_count,
            "filtered_title": filtered_title,
            "filtered_age": filtered_age,
            "filtered_body": filtered_body,
            "last_collection_time": datetime.now().isoformat()
        })
        log(f"  {name}: {new_count} saved, {filtered_title}+{filtered_age}+{filtered_body} filtered")
        save_progress(i, name)

    # Update pipeline state
    pipeline["agents"]["opc-collect"] = {
        "status": "idle",
        "last_run": datetime.now().isoformat(),
        "next_run": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT02:00:00+08:00"),
        "last_output": f"raw-articles/{today}",
        "error": error_log if error_log else None,
        "new_articles_count": total_new
    }
    if total_new > 0:
        pipeline["agents"]["opc-mine"]["status"] = "pending"
    pipeline["stats"]["total_articles_collected"] = pipeline["stats"].get("total_articles_collected", 0) + total_new
    pipeline["last_updated"] = datetime.now().isoformat()
    with open(PIPELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(pipeline, f, ensure_ascii=False, indent=2)

    # Save retry list
    if retry_list:
        os.makedirs(os.path.dirname(RETRY_FILE), exist_ok=True)
        existing_retry = []
        if os.path.exists(RETRY_FILE):
            with open(RETRY_FILE, "r", encoding="utf-8") as f:
                existing_retry = json.load(f)
        existing_retry.extend(retry_list)
        with open(RETRY_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_retry, f, ensure_ascii=False, indent=2)

    log(f"=== Collection Complete ===")
    log(f"  New articles saved: {total_new}")
    log(f"  Filtered: title={total_filtered_title}, age={total_filtered_age}, body={total_filtered_body}")

    if os.path.exists(PROGRESS_FILE):
        try:
            os.remove(PROGRESS_FILE)
        except Exception:
            pass

    if total_new >= 5:
        print(f"\nSUMMARY: Found {total_new} new articles across {len(account_results)} accounts")
        for r in account_results:
            if r.get("new_articles_count", 0) > 0:
                print(f"  - {r['name']}: {r['new_articles_count']} new")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        error_msg = f"[{datetime.now().strftime('%H:%M:%S')}] FATAL ERROR: {e}\n{traceback.format_exc()}"
        print(error_msg, flush=True)
        try:
            with open(r"/app/pipeline-logs/collect-FATAL-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log", "w", encoding="utf-8") as f:
                f.write(error_msg)
        except Exception:
            pass
        sys.exit(1)

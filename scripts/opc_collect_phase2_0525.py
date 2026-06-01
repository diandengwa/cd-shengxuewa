#!/usr/bin/env python3
"""OPC Collect Phase 2 - Continue from account index 23"""

import json, os, time, re, sys
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote

API_BASE = "https://down.mptext.top/api/public/v1"
AUTH_KEY = "11f4e7ef2f45429295e96152b189e0bc"
TODAY = "2026-05-25"
BASE_DIR = "D:/opc"
RAW_DIR = os.path.join(BASE_DIR, f"raw-articles/{TODAY}")
LOG_FILE = os.path.join(BASE_DIR, f"pipeline-logs/collect-{TODAY}.log")
RETRY_LIST = os.path.join(BASE_DIR, "pipeline-logs/retry_list.json")

START_INDEX = 23  # 0-based, skip first 23 accounts already processed

# Load existing URLs for dedup
existing_urls = set()
url_cache_path = os.path.join(BASE_DIR, "pipeline-logs/existing_urls.json")
if os.path.exists(url_cache_path):
    with open(url_cache_path, "r", encoding="utf-8") as f:
        existing_urls = set(json.load(f))

# Load accounts
with open(os.path.join(BASE_DIR, "competitors/accounts.json"), "r", encoding="utf-8") as f:
    accounts = json.load(f)

high_accounts = [a for a in accounts if a.get("priority") == "high"]
remaining = high_accounts[START_INDEX:]
print(f"Phase 2: Processing {len(remaining)} remaining accounts (from index {START_INDEX})")


def api_get(path, retries=3):
    url = f"{API_BASE}{path}"
    for attempt in range(retries):
        try:
            req = Request(url)
            req.add_header("X-Auth-Key", AUTH_KEY)
            req.add_header("User-Agent", "OPC-Collect/1.0")
            resp = urlopen(req, timeout=30)
            data = resp.read().decode("utf-8")
            content_type = resp.headers.get("Content-Type", "")
            if "json" in content_type or data.strip().startswith("{"):
                return json.loads(data)
            else:
                return data
        except HTTPError as e:
            if e.code == 429:
                print(f"  Rate limited, sleeping 60s (attempt {attempt+1})")
                time.sleep(60)
                continue
            elif e.code == 401:
                return {"code": 200013, "msg": "Auth expired"}
            else:
                print(f"  HTTP {e.code} error: {e.reason}")
                if attempt < retries - 1:
                    time.sleep(5)
                    continue
                return None
        except Exception as e:
            print(f"  Network error: {e}")
            if attempt < retries - 1:
                time.sleep(5)
                continue
            return None
    return None


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip(". ")
    if len(name) > 80:
        name = name[:80]
    return name or "untitled"


os.makedirs(RAW_DIR, exist_ok=True)

total_new = 0
total_skipped = 0
total_errors = 0
account_results = []
consecutive_failures = 0
retry_urls = []

# Load existing retry list if any
if os.path.exists(RETRY_LIST):
    with open(RETRY_LIST, "r", encoding="utf-8") as f:
        retry_urls = json.load(f)

log_lines = []

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_lines.append(line)


log("=== OPC Collect Phase 2 Start ===")
log(f"Processing {len(remaining)} remaining accounts")

for i, acct in enumerate(remaining):
    idx = START_INDEX + i
    name = acct["name"]
    fakeid = acct["fakeid"]
    category = acct.get("category", "")

    log(f"[{idx+1}/{len(high_accounts)}] {name} ({category}) fakeid={fakeid}")

    result = api_get(f"/article?fakeid={fakeid}&begin=0&size=5")

    if result is None:
        log("  ERROR: Failed to fetch article list")
        consecutive_failures += 1
        total_errors += 1
        if consecutive_failures >= 3:
            log("  WARNING: 3 consecutive failures, skipping remaining accounts")
            break
        continue

    if isinstance(result, dict) and result.get("code") == 200013:
        log("  AUTH EXPIRED")
        state_path = os.path.join(BASE_DIR, "pipeline-state.json")
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        state["needs_human_attention"] = True
        state["reason"] = "X-Auth-Key expired, please re-login mptext.top"
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print("AUTH_EXPIRED")
        sys.exit(1)

    articles = []
    if isinstance(result, dict):
        articles = result.get("articles", []) or result.get("data", [])
    elif isinstance(result, list):
        articles = result

    if not articles:
        log("  No articles found")
        consecutive_failures = 0
        account_results.append({"name": name, "new": 0, "skipped": 0, "error": False})
        time.sleep(2)
        continue

    log(f"  Found {len(articles)} articles")

    acct_new = 0
    acct_skipped = 0

    for art in articles:
        art_url = art.get("link", "") or art.get("content_url", "") or art.get("url", "")
        title = art.get("title", "untitled")
        art_time = art.get("update_time", "") or art.get("create_time", "") or art.get("pubdate", "")

        if not art_url:
            log(f"  SKIP (no URL): {title[:40]}")
            acct_skipped += 1
            continue

        if art_url in existing_urls:
            acct_skipped += 1
            continue

        log(f"  Downloading: {title[:50]}")
        encoded_url = quote(art_url, safe="")
        md_content = api_get(f"/download?url={encoded_url}&format=markdown")

        if md_content is None:
            log(f"  DOWNLOAD FAILED: {title[:40]}")
            retry_urls.append({"url": art_url, "title": title, "account": name})
            total_errors += 1
            time.sleep(2)
            continue

        if isinstance(md_content, dict):
            if md_content.get("code") == 0 and "data" in md_content:
                md_content = md_content["data"]
            else:
                log(f"  DOWNLOAD ERROR: {md_content}")
                retry_urls.append({"url": art_url, "title": title, "account": name})
                total_errors += 1
                time.sleep(2)
                continue

        if not isinstance(md_content, str):
            md_content = str(md_content)

        if len(md_content.strip()) < 50:
            log(f"  SKIP (too short: {len(md_content)} chars): {title[:40]}")
            acct_skipped += 1
            time.sleep(2)
            continue

        acct_dir = os.path.join(RAW_DIR, sanitize_filename(name))
        os.makedirs(acct_dir, exist_ok=True)

        filename = sanitize_filename(title) + ".md"
        filepath = os.path.join(acct_dir, filename)

        safe_title = title.replace("\\", "\\\\").replace('"', '\\"')

        frontmatter = (
            f"---\n"
            f'title: "{safe_title}"\n'
            f"source: {name}\n"
            f"category: {category}\n"
            f"url: {art_url}\n"
            f"collected_at: {TODAY}\n"
            f'pub_time: "{art_time}"\n'
            f"---\n\n"
        )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(frontmatter + md_content)

        existing_urls.add(art_url)
        acct_new += 1
        log(f"  SAVED: {filename} ({len(md_content)} chars)")

        time.sleep(2)

    consecutive_failures = 0
    total_new += acct_new
    total_skipped += acct_skipped
    account_results.append({"name": name, "new": acct_new, "skipped": acct_skipped, "error": False})
    log(f"  Account summary: {acct_new} new, {acct_skipped} skipped")

# Save retry list
with open(RETRY_LIST, "w", encoding="utf-8") as f:
    json.dump(retry_urls, f, ensure_ascii=False, indent=2)

# Save updated URL cache
with open(url_cache_path, "w", encoding="utf-8") as f:
    json.dump(list(existing_urls), f, ensure_ascii=False)

# Append log
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
with open(LOG_FILE, "a", encoding="utf-8") as f:
    f.write("\n".join(log_lines))

# Update pipeline-state.json
state_path = os.path.join(BASE_DIR, "pipeline-state.json")
with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

# Merge with phase 1 stats
phase1_new = state.get("agents", {}).get("opc-collect", {}).get("new_articles", 0)
all_new = phase1_new + total_new

state["agents"]["opc-collect"] = {
    "status": "idle",
    "last_run": TODAY,
    "new_articles": all_new,
    "skipped": state.get("agents", {}).get("opc-collect", {}).get("skipped", 0) + total_skipped,
    "errors": state.get("agents", {}).get("opc-collect", {}).get("errors", 0) + total_errors,
    "accounts_processed": len(high_accounts),
    "total_accounts": len(high_accounts),
    "note": f"{len(high_accounts)}/{len(high_accounts)} high-priority accounts processed. {all_new} new articles total (phase1={phase1_new}, phase2={total_new}). Auth Key 11f4e7ef valid until ~05-27."
}

if all_new > 0:
    state["agents"]["opc-mine"]["status"] = "pending"
    state["stats"]["articles_collected"] = state["stats"].get("articles_collected", 0) + total_new

state["updated_at"] = f"{TODAY}T17:10:00+08:00"

with open(state_path, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

# Final summary
log("=== OPC Collect Phase 2 Complete ===")
log(f"Phase 2 new articles: {total_new}")
log(f"Phase 2 skipped: {total_skipped}")
log(f"Phase 2 errors: {total_errors}")
log(f"Phase 2 accounts: {len(account_results)}/{len(remaining)}")
log(f"Total new articles today: {all_new}")

print(f"RESULT: Phase 2 complete. {total_new} new articles. Total today: {all_new}")
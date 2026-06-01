#!/usr/bin/env python3
"""OPC Collect Agent - Phase 2: Process remaining high-priority accounts"""

import json, os, time, re, sys
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote

API_BASE = "https://down.mptext.top/api/public/v1"
AUTH_KEY = "11f4e7ef2f45429295e96152b189e0bc"
TODAY = "2026-05-23"
BASE_DIR = "D:/opc"
RAW_DIR = os.path.join(BASE_DIR, f"raw-articles/{TODAY}")

# Remaining accounts to process
REMAINING = [
    {"name": "成都树德中学外国语校区", "fakeid": "MzI3ODE4ODU2Ng==", "category": "名校"},
    {"name": "成都树德中学", "fakeid": "MzA5OTU3OTgwNQ==", "category": "名校"},
    {"name": "成都七中万达学校", "fakeid": "MzA3NjQ2NDcwNA==", "category": "名校"},
    {"name": "天府七中", "fakeid": "MzI0MzU4Nzk5Mw==", "category": "名校"},
    {"name": "成都市七中育才学校", "fakeid": "MzA4MzcwMjkyNQ==", "category": "名校"},
    {"name": "成都七中初中学校", "fakeid": "MzA4NzA0ODY2MA==", "category": "名校"},
    {"name": "四川省成都市第七中学", "fakeid": "MzIzNDU0MjUwNQ==", "category": "名校"},
    {"name": "成都市第七中学", "fakeid": "MzAwMjczNTM5MA==", "category": "名校"},
    {"name": "成都石室天府中学 四中天府", "fakeid": "MzIzMDI2MzAyMA==", "category": "名校"},
]

# Build existing URLs from all raw-articles + knowledge-base
existing_urls = set()

# Scan raw-articles for URL frontmatter
raw_base = os.path.join(BASE_DIR, "raw-articles")
if os.path.exists(raw_base):
    for day_dir in os.listdir(raw_base):
        day_path = os.path.join(raw_base, day_dir)
        if os.path.isdir(day_path):
            for root, dirs, files in os.walk(day_path):
                for fname in files:
                    if fname.endswith(".md"):
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8") as f:
                                content = f.read(3000)
                                if content.startswith("---"):
                                    end = content.find("---", 3)
                                    if end > 0:
                                        frontmatter = content[3:end]
                                        for line in frontmatter.split("\n"):
                                            if line.startswith("url:"):
                                                url = line.split(":", 1)[1].strip().strip("'").strip('"')
                                                if url:
                                                    existing_urls.add(url)
                        except:
                            pass

# Also load knowledge-base index
kb_path = os.path.join(BASE_DIR, "knowledge-base/index.json")
if os.path.exists(kb_path):
    with open(kb_path, "r", encoding="utf-8") as f:
        kb = json.load(f)
    if isinstance(kb, list):
        for item in kb:
            if isinstance(item, dict) and "url" in item:
                existing_urls.add(item["url"])

print(f"Existing URLs for dedup: {len(existing_urls)}")


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
retry_urls = []

log_lines = []

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_lines.append(line)


log("=== OPC Collect Phase 2 Start ===")
log(f"Remaining accounts: {len(REMAINING)}")

consecutive_failures = 0

for i, acct in enumerate(REMAINING):
    name = acct["name"]
    fakeid = acct["fakeid"]
    category = acct.get("category", "")

    log(f"[{i+1}/{len(REMAINING)}] {name} ({category}) fakeid={fakeid}")

    result = api_get(f"/article?fakeid={fakeid}&begin=0&size=5")

    if result is None:
        log("  ERROR: Failed to fetch article list")
        consecutive_failures += 1
        total_errors += 1
        if consecutive_failures >= 3:
            log("  WARNING: 3 consecutive failures, skipping remaining")
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
        sys.exit(1)

    articles = []
    if isinstance(result, dict):
        articles = result.get("articles", []) or result.get("data", [])
    elif isinstance(result, list):
        articles = result

    if not articles:
        log("  No articles found")
        consecutive_failures = 0
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
    log(f"  Account summary: {acct_new} new, {acct_skipped} skipped")

# Save retry list
retry_path = os.path.join(BASE_DIR, "pipeline-logs/retry_list.json")
existing_retries = []
if os.path.exists(retry_path):
    with open(retry_path, "r", encoding="utf-8") as f:
        existing_retries = json.load(f)
existing_retries.extend(retry_urls)
with open(retry_path, "w", encoding="utf-8") as f:
    json.dump(existing_retries, f, ensure_ascii=False, indent=2)

# Append to log file
log_file = os.path.join(BASE_DIR, f"pipeline-logs/collect-{TODAY}.log")
with open(log_file, "a", encoding="utf-8") as f:
    f.write("\n".join(log_lines) + "\n")

log("=== OPC Collect Phase 2 Complete ===")
log(f"Phase 2 new articles: {total_new}")
log(f"Phase 2 skipped: {total_skipped}")
log(f"Phase 2 errors: {total_errors}")

print(f"PHASE2_RESULT: {total_new} new articles collected")

#!/usr/bin/env python3
"""
OPC 采集 Agent - 本地 Windows 版本
路径适配 D:\opc，不依赖服务器模块
"""

import os, json, time, re, sys
from datetime import datetime, timedelta
from pathlib import Path
import requests

# =========================================================
# 配置
# =========================================================
BASE_DIR    = r"D:\opc"
RAW_DIR     = os.path.join(BASE_DIR, "raw-articles")
RETRY_LIST  = os.path.join(RAW_DIR, "_retry_urls.json")
LOG_DIR     = os.path.join(BASE_DIR, "pipeline-logs")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "competitors", "accounts.json")
PIPELINE_STATE = os.path.join(BASE_DIR, "pipeline-state.json")

API_BASE = "https://down.mptext.top/api/public/v1"
AUTH_KEY = "b6873def5062445a8402bb33c63e6415"

# 时效过滤：只采集 N 天内的文章
FRESHNESS_DAYS = 60

# =========================================================
# HTTP Session
# =========================================================
session = requests.Session()
session.headers.update({
    "X-Auth-Key": AUTH_KEY,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    # 同时写文件日志
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = os.path.join(LOG_DIR, f"collect-{today}.log")
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write(line + "\n")
    except Exception:
        pass

def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name)[:80]

def is_too_old(pub_time_str, freshness_days):
    if not pub_time_str:
        return False
    try:
        pub_dt = datetime.fromtimestamp(int(pub_time_str[:10]))
        cutoff = datetime.now() - timedelta(days=freshness_days)
        return pub_dt < cutoff
    except Exception:
        return False

# =========================================================
# API 调用
# =========================================================
def call_api_list_articles(fakeid, limit=50, retry=3):
    """获取文章列表"""
    url = f"{API_BASE}/article"
    params = {"fakeid": fakeid, "begin": 0, "size": limit}
    for attempt in range(retry):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            # 检查错误码
            if isinstance(data, dict):
                # 可能的错误格式
                if data.get("code") == -1 or data.get("base_resp", {}).get("ret", 0) != 0:
                    log(f"  API error: {data}")
                    if attempt < retry - 1:
                        time.sleep(5)
                        continue
                    return None
            return data
        except Exception as e:
            log(f"  API list error (attempt {attempt+1}/{retry}): {e}")
            if attempt < retry - 1:
                time.sleep(5)
            else:
                return None
    return None

def call_api_download(article_url, retry=3):
    """下载文章内容（返回 markdown 文本）"""
    url = f"{API_BASE}/download"
    params = {"url": article_url, "format": "markdown"}
    for attempt in range(retry):
        try:
            resp = session.get(url, params=params, timeout=60)
            resp.raise_for_status()
            text = resp.text
            # API 返回纯文本 markdown（非 JSON）
            if len(text) < 50:
                log(f"  Download: suspiciously short response ({len(text)} chars)")
                return None
            return text
        except Exception as e:
            log(f"  API download error (attempt {attempt+1}/{retry}): {e}")
            if attempt < retry - 1:
                time.sleep(10)
            else:
                return None
    return None

# =========================================================
# 主采集逻辑
# =========================================================
def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    today = today_str()
    log(f"=== OPC Collect v5 (Local Windows) ===")
    log(f"Today: {today}")
    log(f"RAW_DIR: {RAW_DIR}")
    log(f"FRESHNESS_DAYS: {FRESHNESS_DAYS}")

    # 读取账号列表
    if not os.path.exists(ACCOUNTS_FILE):
        log(f"ERROR: accounts.json not found: {ACCOUNTS_FILE}")
        return

    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        accounts = json.load(f)

    # 只处理 high priority
    high_accounts = [a for a in accounts if a.get("priority") == "high"]
    # 按 name 排序（稳定顺序）
    high_accounts.sort(key=lambda x: x.get("name", ""))
    log(f"High-priority accounts: {len(high_accounts)}")

    # 加载已有 URL 去重（扫描 raw-articles 下所有 md 文件的 frontmatter）
    existing_urls = set()
    log("Building URL cache from existing articles...")
    for root, dirs, files in os.walk(RAW_DIR):
        for fname in files:
            if fname.endswith(".md"):
                try:
                    fpath = os.path.join(root, fname)
                    with open(fpath, "r", encoding="utf-8", errors="replace") as ff:
                        content = ff.read(2000)
                        # 从 YAML frontmatter 提取 url:
                        m = re.search(r'^url:\s*(.+)$', content, re.MULTILINE)
                        if m:
                            existing_urls.add(m.group(1).strip())
                except Exception:
                    pass
    log(f"URL cache: {len(existing_urls)} existing articles")

    # 加载 retry list
    retry_urls = []
    if os.path.exists(RETRY_LIST):
        try:
            with open(RETRY_LIST, "r", encoding="utf-8") as f:
                retry_urls = json.load(f)
            log(f"Loaded {len(retry_urls)} retry URLs")
        except Exception:
            pass

    # 先尝试 retry URLs
    if retry_urls:
        log(f"\n--- Retrying {len(retry_urls)} previously failed URLs ---")
        new_retry = []
        for url in retry_urls:
            md = call_api_download(url)
            if md:
                log(f"  Retry success: {url[:60]}...")
                existing_urls.add(url)
            else:
                new_retry.append(url)
            time.sleep(2)
        with open(RETRY_LIST, "w", encoding="utf-8") as f:
            json.dump(new_retry, f, ensure_ascii=False, indent=2)
        log(f"Retry done: {len(retry_urls) - len(new_retry)} success, {len(new_retry)} still failing")

    # 遍历高优先级账号
    total_new      = 0
    total_skipped  = 0
    total_filtered = 0
    total_errors   = 0
    account_results = []
    failed_accounts = 0

    for idx, acct in enumerate(high_accounts, 1):
        name    = acct.get("name", f"unknown-{idx}")
        fakeid  = acct.get("fakeid", "")
        if not fakeid:
            continue

        log(f"\n[{idx}/{len(high_accounts)}] Account: {name}")

        # 连续失败检测
        if failed_accounts >= 3:
            log(f"WARNING: {failed_accounts} consecutive failures, skipping remaining accounts")
            break

        # 1. 获取文章列表
        list_data = call_api_list_articles(fakeid, limit=5)
        if not list_data:
            log(f"  Failed to fetch article list")
            total_errors += 1
            failed_accounts += 1
            account_results.append({"name": name, "new": 0, "skipped": 0, "filtered": 0, "error": True})
            continue

        # 文章列表可能在 data 或 articles 字段
        articles = []
        if isinstance(list_data, dict):
            articles = list_data.get("data", list_data.get("articles", []))
        if not isinstance(articles, list):
            articles = []

        if not articles:
            log(f"  No articles returned")
            failed_accounts = 0  # 重置连续失败计数
            account_results.append({"name": name, "new": 0, "skipped": 0, "filtered": 0, "error": False})
            continue

        log(f"  Fetched {len(articles)} articles")

        acct_new      = 0
        acct_skipped  = 0
        acct_filtered = 0
        failed_accounts = 0  # 重置连续失败计数

        for art in articles:
            art_url  = art.get("link", art.get("url", ""))
            art_time = str(art.get("update_time", art.get("publish_time", "")))
            title    = art.get("title", "untitled")

            if not art_url:
                continue

            # 去重
            if art_url in existing_urls:
                acct_skipped += 1
                continue

            # 时效过滤
            if is_too_old(art_time, FRESHNESS_DAYS):
                acct_filtered += 1
                continue

            # 下载文章内容
            log(f"  Downloading: {title[:40]}...")
            md_content = call_api_download(art_url)
            if not md_content:
                log(f"    Download failed, adding to retry list")
                retry_urls.append(art_url)
                time.sleep(3)
                continue

            # 判断分类
            category = "policy" if any(kw in title for kw in ["政策", "通知", "公告", "办法", "规定"]) else "news"

            # 保存为 MD
            acct_dir = os.path.join(RAW_DIR, today, sanitize_filename(name))
            os.makedirs(acct_dir, exist_ok=True)
            filename = sanitize_filename(title) + ".md"

            # 解析发布时间
            try:
                pub_time_str = datetime.fromtimestamp(int(art_time[:10])).strftime("%Y-%m-%d %H:%M:%S") if art_time else today
            except Exception:
                pub_time_str = today

            front_matter = (
                f"---\n"
                f'title: "{title.replace(chr(34), chr(92)+chr(34))}"\n'
                f"source: {name}\n"
                f"category: {category}\n"
                f"url: {art_url}\n"
                f"collected_at: {today}\n"
                f'pub_time: "{pub_time_str}"\n'
                f"---\n\n"
            )

            filepath = os.path.join(acct_dir, filename)
            try:
                with open(filepath, "w", encoding="utf-8", errors="replace") as f:
                    f.write(front_matter + md_content)
            except UnicodeEncodeError:
                # GBK 兜底
                with open(filepath, "w", encoding="utf-8", errors="replace") as f:
                    f.write(front_matter + md_content)

            existing_urls.add(art_url)
            acct_new += 1
            total_new += 1
            log(f"    SAVED: {filename} ({len(md_content)} chars)")
            time.sleep(2)

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
    if os.path.exists(PIPELINE_STATE):
        try:
            with open(PIPELINE_STATE, "r", encoding="utf-8") as f:
                state = json.load(f)
            state.setdefault("agents", {})
            state["agents"]["opc-collect"] = {
                "status": "done",
                "last_run": today,
                "new_articles": total_new,
                "skipped": total_skipped,
                "filtered": total_filtered,
                "errors": total_errors,
                "accounts_processed": len(account_results),
            }
            if total_new > 0:
                state["agents"]["opc-mine"] = state.get("agents", {}).get("opc-mine", {})
                state["agents"]["opc-mine"]["status"] = "pending"
            state["updated_at"] = now_iso()
            with open(PIPELINE_STATE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            log(f"\nPipeline state updated: opc-collect.status = done, last_run = {today}")
            if total_new > 0:
                log(f"opc-mine.status set to pending (triggering next step)")
        except Exception as e:
            log(f"ERROR updating pipeline-state.json: {e}")

    log("=== OPC Collect Complete ===")
    log(f"Total new articles: {total_new}")
    log(f"Total skipped (existing): {total_skipped}")
    log(f"Total filtered (too old): {total_filtered}")
    log(f"Total errors: {total_errors}")

    # 输出摘要（新文章 >= 5 时）
    if total_new >= 5:
        print(f"\n=== COLLECTION SUMMARY ===")
        print(f"Date: {today}")
        print(f"New articles: {total_new}")
        print(f"Skipped: {total_skipped}")
        print(f"Filtered (too old): {total_filtered}")
        print(f"Errors: {total_errors}")
        print(f"Accounts processed: {len(account_results)}")
        # 打印各账号新增数
        for r in account_results:
            if r.get("new", 0) > 0:
                print(f"  {r['name']}: {r['new']} new")

    return total_new

if __name__ == "__main__":
    main()

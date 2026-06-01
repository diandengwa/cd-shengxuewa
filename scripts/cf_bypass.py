#!/usr/bin/env python3
"""用 Playwright 绕过 Cloudflare，获取 mptext API 数据"""
from playwright.sync_api import sync_playwright
import json, time, sys, urllib.parse

API_KEY  = "b6873def5062445a8402bb33c63e6415"
BASE_URL = "https://down.mptext.top/api/public/v1"

def fetch_articles(fakeid, limit=50):
    """用 Playwright 绕过 CF，获取文章列表"""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = ctx.new_page()

        # 1. 先访问主页，让 CF cookie 种上
        print('[CF] Step 1: 访问主页...', flush=True)
        try:
            page.goto('https://down.mptext.top/', timeout=30000)
            time.sleep(5)  # 等 CF 挑战完成
        except Exception as e:
            print(f'[CF] 主页访问失败(忽略): {e}', flush=True)

        # 2. 调 API（带着 CF cookie）
        params = urllib.parse.urlencode({'fakeid': fakeid, 'limit': limit})
        api_url = f'{BASE_URL}/articles?{params}'
        print(f'[CF] Step 2: 调 API {api_url[:80]}...', flush=True)

        try:
            resp = page.goto(api_url, timeout=20000)
            time.sleep(2)
            status = resp.status if resp else 0
            print(f'[CF] Status: {status}', flush=True)
        except Exception as e:
            print(f'[CF] API goto 失败: {e}', flush=True)
            browser.close()
            return None

        # 3. 提取页面 JSON
        try:
            # 尝试从 <pre> 标签拿 JSON
            if page.locator('pre').count() > 0:
                text = page.locator('pre').inner_text()
            else:
                text = page.content()
            # 去掉 HTML 标签，只保留 JSON
            import re
            # 找 JSON 开头
            idx = text.find('{"')
            if idx == -1:
                idx = text.find('[{"')
            if idx != -1:
                text = text[idx:]
            data = json.loads(text)
            print('[CF] JSON 解析成功', flush=True)
            browser.close()
            return data
        except Exception as e:
            print(f'[CF] JSON 解析失败: {e}', flush=True)
            # 尝试直接拿 response body
            try:
                body = resp.body() if resp else b''
                text = body.decode('utf-8', errors='ignore')
                idx = text.find('{"')
                if idx != -1:
                    data = json.loads(text[idx:])
                    print('[CF] 从 body 解析 JSON 成功', flush=True)
                    browser.close()
                    return data
            except Exception as e2:
                print(f'[CF] body 解析也失败: {e2}', flush=True)

            # debug: 打印页面内容
            content = page.content()
            print(f'[CF] Page content[:500]: {content[:500]}', flush=True)
            browser.close()
            return None

if __name__ == '__main__':
    fakeid = sys.argv[1] if len(sys.argv) > 1 else 'MzIzMjQ0MTIzOQ=='
    limit  = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f'fakeid={fakeid}, limit={limit}')
    result = fetch_articles(fakeid, limit=limit)
    if result:
        print('SUCCESS:', json.dumps(result, ensure_ascii=False)[:500])
    else:
        print('FAILED')
        sys.exit(1)

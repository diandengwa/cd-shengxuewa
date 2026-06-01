#!/usr/bin/env python3
"""用 Playwright 真实浏览器绕过 Cloudflare，获取文章列表"""
from playwright.sync_api import sync_playwright
import json, time, sys, urllib.parse, re

API_KEY  = "b6873def5062445a8402bb33c63e6415"
BASE_URL = "https://down.mptext.top/api/public/v1"

def fetch_articles(fakeid, limit=50, days=60):
    """用 Playwright 绕过 CF，获取文章列表，返回 list"""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800},
        )
        page = ctx.new_page()

        # 1. 先访问主页，让 CF cookie 种上
        print('[CF] Step 1: 访问主页...', flush=True)
        try:
            page.goto('https://down.mptext.top/', timeout=30000)
            time.sleep(5)
            print(f'  title: {page.title()}', flush=True)
        except Exception as e:
            print(f'  [WARN] 主页访问异常(继续): {e}', flush=True)

        # 2. 调 articles 端点（带着 CF cookie）
        params = urllib.parse.urlencode({'fakeid': fakeid, 'page': 1, 'limit': limit})
        api_url = f'{BASE_URL}/articles?{params}'
        print(f'[CF] Step 2: GET {api_url[:100]}...', flush=True)

        try:
            resp = page.goto(api_url, timeout=20000)
            time.sleep(3)
            status = resp.status if resp else 0
            print(f'  status: {status}', flush=True)
        except Exception as e:
            print(f'  [ERROR] goto 失败: {e}', flush=True)
            browser.close()
            return None

        # 3. 提取 JSON（优先找 <pre>，否则找 body 文本）
        try:
            # 尝试 <pre> 标签
            pre_count = page.locator('pre').count()
            if pre_count > 0:
                text = page.locator('pre').inner_text()
            else:
                # 直接拿 body inner_text
                text = page.locator('body').inner_text()
            
            # 找 JSON 起始位置
            idx = text.find('{"')
            if idx == -1:
                idx = text.find('[{"')
            if idx != -1:
                text = text[idx:]
            
            data = json.loads(text)
            
            # 检查 base_resp
            if isinstance(data, dict) and data.get('base_resp', {}).get('ret', 0) == 0:
                articles = data.get('list', [])
                print(f'  [OK] 拿到 {len(articles)} 篇文章', flush=True)
                browser.close()
                return articles
            else:
                print(f'  [WARN] API 返回错误: {data.get("base_resp")}', flush=True)
        except json.JSONDecodeError as e:
            print(f'  [WARN] JSON 解析失败: {e}', flush=True)
            # debug: 打印页面内容
            content = page.content()
            # 去掉 HTML 标签，找 JSON
            body_text = page.locator('body').inner_text()
            idx = body_text.find('{"')
            if idx != -1:
                try:
                    data = json.loads(body_text[idx:])
                    articles = data.get('list', [])
                    print(f'  [OK] 从 body 解析到 {len(articles)} 篇', flush=True)
                    browser.close()
                    return articles
                except:
                    pass
            print(f'  [DEBUG] body[:300]: {body_text[:300]}', flush=True)
        except Exception as e:
            print(f'  [ERROR] 提取失败: {e}', flush=True)

        browser.close()
        return None

if __name__ == '__main__':
    fakeid = sys.argv[1] if len(sys.argv) > 1 else 'MzIzMjQ0MTIzOQ=='
    limit  = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    print(f'fakeid={fakeid}, limit={limit}')
    result = fetch_articles(fakeid, limit=limit)
    if result:
        print(json.dumps(result, ensure_ascii=False)[:600])
    else:
        print('FAILED')
        sys.exit(1)

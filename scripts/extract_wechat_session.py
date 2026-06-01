"""
Extract WeChat MP session info from Chrome via CDP.
Try to get cookies and see if we can make authenticated API calls.
"""
import asyncio
import json
from pathlib import Path

LOG_DIR = Path("D:/opc/pipeline-logs")

async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        print("Connecting to Chrome CDP...")
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        print(f"URL: {page.url[:100]}")

        # Get all cookies
        cookies = await context.cookies()
        print(f"\nFound {len(cookies)} cookies:")
        for c in cookies[:10]:
            print(f"  {c['name']} = {str(c['value'])[:30]}  (domain: {c['domain']})")

        # Save cookies to file for potential API use
        cookie_file = LOG_DIR / "wechat-cookies.json"
        with open(cookie_file, "w") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        print(f"\nCookies saved to: {cookie_file}")

        # Try to make an API call using the session
        # WeChat MP's internal API might accept cookie-based auth
        print("\nTrying to fetch draft list via API...")

        import re
        token_match = re.search(r'token=(\d+)', page.url)
        token = token_match.group(1) if token_match else ""

        if token:
            # Try the draft list API
            api_url = f"https://mp.weixin.qq.com/cgi-bin/appmsg?action=list&type=10&lang=zh_CN&token={token}&offset=0&count=10"
            print(f"Trying API: {api_url[:80]}...")

            try:
                response = await page.evaluate(f"""async (url) => {{
                    const resp = await fetch(url, {{
                        method: 'GET',
                        credentials: 'include',
                    }});
                    return await resp.text();
                }}""", api_url)
                print(f"API response (first 500 chars): {response[:500]}")
            except Exception as e:
                print(f"API call failed: {e}")

        print("\nDone. Check saved cookies for potential API use.")

asyncio.run(main())

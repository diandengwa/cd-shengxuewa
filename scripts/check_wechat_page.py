"""
Simple script to check WeChat MP page state and find drafts.
"""
import asyncio
import re
from pathlib import Path

LOG_DIR = Path("D:/opc/pipeline-logs")

async def main():
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        print("Connecting to Chrome CDP...")
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        
        print(f"\nCurrent URL: {page.url}")
        print(f"Title: {await page.title()}")
        
        # Get token
        token_match = re.search(r'token=(\d+)', page.url)
        token = token_match.group(1) if token_match else ""
        print(f"Token: {token[:20] if token else '(not found)'}")
        
        # Go to draft box page
        # WeChat MP draft box URL
        draft_url = f"https://mp.weixin.qq.com/cgi-bin/appmsg?action=list&type=10&lang=zh_CN&token={token}"
        print(f"\nNavigating to draft list: {draft_url[:80]}...")
        
        await page.goto(draft_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(5)
        
        print(f"After nav URL: {page.url}")
        
        # Screenshot
        ss_path = LOG_DIR / "wechat-draft-box.png"
        await page.screenshot(path=str(ss_path), full_page=True)
        print(f"Screenshot: {ss_path}")
        
        # Get page text
        text = await page.evaluate("() => document.body.innerText")
        print(f"\nPage text (first 2000 chars):")
        print(text[:2000])
        
        # Check for our drafts
        for keyword in ["小升初", "幼儿园"]:
            if keyword in text:
                print(f"\n[FOUND] '{keyword}' found in page!")
        
        # Check if we need to login
        if "login" in page.url.lower():
            print("\nLOGIN REQUIRED - please scan QR in Chrome window")
        
        print("\nDone. Check screenshot at:", ss_path)

asyncio.run(main())

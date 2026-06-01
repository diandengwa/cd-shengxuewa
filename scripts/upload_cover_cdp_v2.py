"""
Upload cover images to WeChat Official Account drafts via Chrome CDP.
Connects to existing Chrome (with logged-in session) and uploads cover images to drafts.
"""
import asyncio
import os
import json
import sys
from pathlib import Path

COVER_DIR = Path("D:/opc/ready-to-publish/2026-05-23/imgs")
LOG_DIR = Path("D:/opc/pipeline-logs")
CDP_URL = "http://127.0.0.1:9222"

DRAFTS = [
    {
        "title_keyword": "小升初被多校同时录取",
        "cover": COVER_DIR / "小升初_cover.png",
    },
    {
        "title_keyword": "幼儿园摇号没中",
        "cover": COVER_DIR / "幼儿园_cover.png",
    },
]

async def find_token_from_page(page):
    """Try to extract WeChat MP token from page."""
    # Token is usually in the page URL or in a JS variable
    url = page.url
    import re
    m = re.search(r'token=(\d+)', url)
    if m:
        return m.group(1)
    
    # Try to get from page content
    token = await page.evaluate("""() => {
        // WeChat MP stores token in various places
        if (window.wx_common_uin) return window.wx_common_uin;
        if (window.uin) return window.uin;
        // Try meta tags
        const meta = document.querySelector('meta[name="token"]');
        if (meta) return meta.content;
        return null;
    }""")
    return token


async def main():
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        print("Connecting to Chrome via CDP...")
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        
        contexts = browser.contexts
        if not contexts:
            print("ERROR: No browser contexts found. Is Chrome running with --remote-debugging-port=9222?")
            return
        
        context = contexts[0]
        pages = context.pages
        page = pages[0] if pages else await context.new_page()
        
        print(f"Connected! Current URL: {page.url}")
        
        # Navigate to draft management page
        print("\nNavigating to WeChat MP draft list...")
        draft_list_url = "https://mp.weixin.qq.com/cgi-bin/appmsg?action=list&type=10&lang=zh_CN&token="
        
        # First go to main page to get token
        await page.goto("https://mp.weixin.qq.com/", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)
        
        current_url = page.url
        print(f"After navigation URL: {current_url}")
        
        # Extract token
        import re
        token_match = re.search(r'token=(\d+)', current_url)
        if not token_match:
            # Try to find token in page
            print("Token not in URL, trying to extract from page...")
            html = await page.content()
            token_match = re.search(r'"token"\s*:\s*"?(\d+)"?', html)
        
        if token_match:
            token = token_match.group(1)
            print(f"Found token: {token}")
        else:
            print("WARNING: Could not find token. Will try to proceed anyway...")
            token = ""
        
        # Now go to draft list (type=10 is drafts)
        draft_url = f"https://mp.weixin.qq.com/cgi-bin/appmsg?action=list&type=10&lang=zh_CN&token={token}"
        print(f"\nNavigating to draft list: {draft_url}")
        await page.goto(draft_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)
        
        # Take screenshot
        ss_path = LOG_DIR / "wechat-draft-list.png"
        await page.screenshot(path=str(ss_path), full_page=True)
        print(f"Screenshot saved: {ss_path}")
        
        # Get page text to see what's there
        page_text = await page.evaluate("() => document.body.innerText")
        print(f"\nPage text (first 1000 chars):\n{page_text[:1000]}")
        
        # Try to find our draft articles
        for draft in DRAFTS:
            keyword = draft["title_keyword"]
            print(f"\n--- Looking for draft: {keyword} ---")
            
            if keyword in page_text:
                print(f"Found '{keyword}' in page text!")
            else:
                print(f"'{keyword}' NOT found in page text")
        
        # Keep browser open for manual inspection
        print("\nBrowser staying open. Check the Chrome window to see the draft list.")
        print("Press Enter to close...")
        input()

asyncio.run(main())

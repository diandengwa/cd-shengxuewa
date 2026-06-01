"""
Upload cover images to WeChat Official Account drafts via Chrome CDP.
Uses Playwright to connect to an existing Chrome instance.

Strategy: 
1. Navigate to draft edit page for each article
2. Find the cover image upload area
3. Upload the cover image file
4. Save and return to draft list
"""
import asyncio
import os
import sys
import json
from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"
COVER_DIR = "D:/opc/ready-to-publish/2026-05-23/imgs"
LOG_DIR = "D:/opc/pipeline-logs"

DRAFTS = [
    {
        "title": "小升初被多校同时录取",
        "media_id": "504031705",
        "cover": os.path.join(COVER_DIR, "小升初_cover.png"),
    },
    {
        "title": "幼儿园摇号没中",
        "media_id": "504031706",
        "cover": os.path.join(COVER_DIR, "幼儿园_cover.png"),
    },
]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        contexts = browser.contexts
        if not contexts:
            print("ERROR: No browser contexts found")
            return
        
        page = contexts[0].pages[0] if contexts[0].pages else await contexts[0].new_page()
        
        # Step 1: Navigate to draft management page (草稿箱)
        print("Step 1: Navigating to draft box...")
        await page.goto("https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&lang=zh_CN", 
                        wait_until="networkidle", timeout=30000)
        
        # Check current page state
        current_url = page.url
        print(f"Current URL: {current_url}")
        print(f"Page title: {await page.title()}")
        
        # Take screenshot
        await page.screenshot(path=os.path.join(LOG_DIR, "wechat-step1-draftlist.png"), full_page=True)
        print("Screenshot saved: wechat-step1-draftlist.png")
        
        # Check if we need login
        if "login" in current_url.lower() or "bizlogin" in current_url.lower():
            print("NEED LOGIN! Please scan QR code in the Chrome window.")
            await page.wait_for_url("**/appmsg**", timeout=120000)
            print("Login successful!")
        
        # Step 2: Try to find draft articles in the list
        print("Step 2: Looking for draft articles...")
        
        # Wait for content to load
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(3)
        
        # Get page text content to understand current state
        body_text = await page.evaluate("() => document.body.innerText")
        print(f"Page body text (first 500 chars): {body_text[:500]}")
        
        # Look for draft items - try multiple selectors
        # WeChat MP draft page typically has article items with titles
        selectors_to_try = [
            ".appmsg_item",           # old UI
            ".weui-desktop-draft__item", # newer UI
            "[data-type='draft']",     # possible data attr
            ".draft-item",
            ".card_appmsg_item",
            "li.appmsg_item",
            ".weui-desktop-appmsg__item",
        ]
        
        found_items = []
        for sel in selectors_to_try:
            items = await page.query_selector_all(sel)
            if items:
                print(f"Found {len(items)} items with selector: {sel}")
                found_items = items
                break
        
        if not found_items:
            print("No draft items found with standard selectors. Trying to get all visible text elements...")
            # Try to find any element containing our article title
            all_elements = await page.evaluate("""() => {
                const els = document.querySelectorAll('*');
                const results = [];
                for (const el of els) {
                    if (el.innerText && el.innerText.includes('小升初') || el.innerText && el.innerText.includes('幼儿园摇号')) {
                        results.push({
                            tag: el.tagName,
                            text: el.innerText.substring(0, 100),
                            id: el.id,
                            className: el.className
                        });
                    }
                }
                return results;
            }""")
            print(f"Elements containing article titles: {json.dumps(all_elements[:10], ensure_ascii=False)}")
            
            # Also check the page HTML for clues
            html_snippet = await page.evaluate("() => document.body.innerHTML.substring(0, 3000)")
            print(f"HTML snippet: {html_snippet[:1000]}")
        
        # Step 3: Try alternative approach - go directly to edit each draft via media_id
        print("Step 3: Trying to edit drafts directly...")
        
        for draft in DRAFTS:
            print(f"\nProcessing draft: {draft['title']} (media_id: {draft['media_id'])}")
            
            # WeChat draft edit URL format
            # Try the direct edit URL
            edit_url = f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&lang=zh_CN&token={token}"
            
            # Actually, we need to find the token first
            # Let me extract it from the current page URL or cookies
            pass

asyncio.run(main())
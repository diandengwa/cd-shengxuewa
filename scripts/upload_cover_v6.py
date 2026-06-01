"""
Upload cover images to WeChat MP drafts - working version.
The page is already on the draft list (action=list&type=10).
"""
import asyncio
from pathlib import Path

COVER_DIR = Path("D:/opc/ready-to-publish/2026-05-23/imgs")
LOG_DIR = Path("D:/opc/pipeline-logs")

DRAFTS = [
    {"keyword": "小升初被多校同时录取", "cover": str(COVER_DIR / "小升初_cover.png")},
    {"keyword": "幼儿园摇号没中",       "cover": str(COVER_DIR / "幼儿园_cover.png")},
]

async def take_screenshot(page, name):
    path = LOG_DIR / f"wechat-{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"  Screenshot: {path.name}")
    return path

async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        print("Connecting to Chrome CDP...")
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        print(f"\nCurrent URL: {page.url[:100]}")
        await take_screenshot(page, "01-draft-list")

        # ===== Step 1: Get page text to see drafts =====
        print("\n=== Step 1: Checking draft list ===")
        page_text = await page.evaluate("() => document.body.innerText")
        print(f"  Page text length: {len(page_text)}")

        for d in DRAFTS:
            kw = d["keyword"]
            if kw in page_text:
                print(f"  [FOUND] {kw[:15]}")
            else:
                print(f"  [MISSING] {kw[:15]}")

        # ===== Step 2: Find and click "编辑" for first draft =====
        print("\n=== Step 2: Finding edit buttons ===")

        # Get all "编辑" buttons/links
        edit_buttons = await page.query_selector_all("text=编辑")
        print(f"  Found {len(edit_buttons)} elements with '编辑' text")

        if not edit_buttons:
            # Try links
            edit_links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a, button'))
                    .filter(el => el.innerText && el.innerText.trim() === '编辑')
                    .map(el => ({tag: el.tagName, text: el.innerText.trim(), href: el.href || ''}));
            }""")
            print(f"  Found via JS: {len(edit_links)} edit elements")
            for item in edit_links[:5]:
                print(f"    {item}")

        # ===== Step 3: Try to find draft rows =====
        print("\n=== Step 3: Finding draft rows ===")
        
        # Look for elements containing our draft titles
        for d in DRAFTS:
            kw = d["keyword"]
            print(f"\n  Looking for: {kw[:20]}")
            
            # Try to find element containing this text
            elem = await page.query_selector(f"text={kw[:10]}")
            if elem:
                print(f"    Found element containing keyword!")
                # Get the parent row
                row = await elem.evaluate("""(el) => {
                    let cur = el;
                    for (let i = 0; i < 15; i++) {
                        if (!cur.parentElement) break;
                        cur = cur.parentElement;
                        const cls = cur.className || '';
                        const tag = cur.tagName || '';
                        if (tag === 'LI' || tag === 'TR' || cls.includes('item') || cls.includes('row')) {
                            return {tag, class: cls, html: cur.outerHTML.substring(0, 500)};
                        }
                    }
                    return {tag: cur.tagName, class: cur.className, html: cur.outerHTML.substring(0, 300)};
                }""")
                print(f"    Parent row: {row}")
            else:
                print(f"    No element found for '{kw[:10]}'")

        # ===== Step 4: Get all links on page =====
        print("\n=== Step 4: Getting all links ===")
        all_links = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]'))
                .filter(a => a.href && a.href.includes('weixin.qq.com'))
                .map(a => ({href: a.href.substring(0, 100), text: (a.innerText || '').trim().substring(0, 30)}));
        }""")
        print(f"  Found {len(all_links)} links to WeChat MP")
        for link in all_links[:15]:
            print(f"    {link}")

        # ===== Step 5: Try direct navigation to edit page =====
        # WeChat draft edit URL format (guessing):
        # https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&lang=zh_CN&token=TOKEN
        print("\n=== Step 5: Trying direct navigation ===")
        
        import re
        token_match = re.search(r'token=(\d+)', page.url)
        token = token_match.group(1) if token_match else ""
        
        # Try the edit URL - WeChat uses appmsgid to identify drafts
        # The media_id from API (504031705, 504031706) might be the appmsgid
        for d in DRAFTS:
            # Try different URL formats
            urls_to_try = [
                f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&lang=zh_CN&token={token}",
                f"https://mp.weixin.qq.com/cgi-bin/appmsg?action=edit&type=77&lang=zh_CN&token={token}",
            ]
            print(f"\n  For draft: {d['keyword'][:15]}")
            for url in urls_to_try:
                print(f"    Trying: {url[:80]}")
        
        print("\n=== Keeping browser open for inspection ===")
        print("Check the Chrome window. Screenshot saved to:", LOG_DIR)
        await asyncio.sleep(600)

asyncio.run(main())

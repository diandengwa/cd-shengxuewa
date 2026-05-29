"""
Fetch 5 district 初中划片 pages from Chengdu Education Bureau using Playwright.
These pages have JS anti-scraping, so we need a real browser.
"""
import asyncio
import os
import re
from playwright.async_api import async_playwright

URLS = {
    "武侯区": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_749d1ae700e94d9db261abacb8fafb2b.shtml",
    "高新区": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_aff212e71101404a9470a830eedb5d2d.shtml",
    "龙泉驿区": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_b40a4fffbcf8463493e25432bf19ee80.shtml",
    "双流区": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_dce92dbae0554e5596451b4837ddc9bc.shtml",
    "郫都区": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_7167efcc82c0475eaf4587d6b67c5cc3.shtml",
}

OUTPUT_DIR = r"D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_初中划片"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
            viewport={"width": 1920, "height": 1080}
        )
        
        results = {}
        for district, url in URLS.items():
            page = await context.new_page()
            try:
                print(f"Fetching {district}...")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait for JS anti-scraping to resolve
                await page.wait_for_timeout(8000)
                
                # Try waiting for actual content to appear
                try:
                    await page.wait_for_function(
                        """() => {
                            const body = document.body.innerText;
                            return body && body.trim().length > 50 && !body.includes('请输入验证码');
                        }""",
                        timeout=15000
                    )
                except:
                    print(f"  ⚠ Content wait timeout for {district}, trying anyway...")
                
                # Take screenshot for debugging
                screenshot_path = os.path.join(OUTPUT_DIR, f"screenshot_{district}.png")
                await page.screenshot(path=screenshot_path)
                print(f"  Screenshot saved: {screenshot_path}")
                
                # Get content
                content = await page.evaluate("""() => {
                    const selectors = [
                        '.article-content', '.content', '#content', 
                        '.detail-content', '.text-content', '.TRS_Editor',
                        'article', '.main-content', '.page-content',
                        '.zoom', '#zoom', '.Custom_UnionStyle',
                        '.detail', '.detail_info', '.info-content'
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.trim().length > 100) {
                            return el.innerText;
                        }
                    }
                    return document.body.innerText;
                }""")
                
                filename = f"2025_{district}_初中划片_official.txt"
                filepath = os.path.join(OUTPUT_DIR, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"来源: {url}\n")
                    f.write(f"区县: {district}\n")
                    f.write(f"级别: 初中划片\n")
                    f.write("=" * 60 + "\n\n")
                    f.write(content)
                
                print(f"  ✓ {district}: saved {len(content)} chars")
                results[district] = content
            except Exception as e:
                print(f"  ✗ {district}: {e}")
                results[district] = None
            finally:
                await page.close()
        
        await browser.close()
        
        # Summary
        print("\n" + "=" * 60)
        print("Summary:")
        for district, content in results.items():
            status = f"✓ {len(content)} chars" if content else "✗ FAILED"
            print(f"  {district}: {status}")

if __name__ == "__main__":
    asyncio.run(main())

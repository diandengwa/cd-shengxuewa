"""
Fetch 5 district 初中划片 from WeChat articles using Playwright.
"""
import asyncio
import os
from playwright.async_api import async_playwright

URLS = {
    "武侯区": "https://mp.weixin.qq.com/s?__biz=MzI0MTEyMTI2Mg==&mid=2651242758&idx=1&sn=3b424a7ff7678b03747bed98cce40dc0",
    "高新区": "https://mp.weixin.qq.com/s?__biz=Mzk0MTM5MTU3MA==&mid=2247639648&idx=1&sn=bb9261d4a158e6278debdab74ff7156a",
    "龙泉驿区": "https://mp.weixin.qq.com/s?__biz=MzA3ODUwMzIxNA==&mid=2651366061&idx=1&sn=c446f90fdc8b5cde317c63f3ada200c3",
    "双流区": "https://mp.weixin.qq.com/s?__biz=MzAwMjI1NTkzMw==&mid=2652208102&idx=1&sn=4093a655d0b34f200bbf2b7a04166324",
    "郫都区": "https://mp.weixin.qq.com/s?__biz=MzIxNTA0ODI3NA==&mid=2651110290&idx=1&sn=bdf45f6d20e3759db63ad0931611da9a",
}

OUTPUT_DIR = r"D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_初中划片"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel='chrome',
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        
        for district, url in URLS.items():
            page = await context.new_page()
            try:
                print(f"\nFetching {district}...")
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_timeout(5000)
                
                # WeChat articles use js_content div
                content = await page.evaluate("""() => {
                    const jsContent = document.querySelector('#js_content');
                    if (jsContent) {
                        return jsContent.innerText;
                    }
                    // Fallback
                    const richMediaContent = document.querySelector('.rich_media_content');
                    if (richMediaContent) {
                        return richMediaContent.innerText;
                    }
                    return document.body.innerText;
                }""")
                
                if content and len(content.strip()) > 50:
                    filename = f"2025_{district}_初中划片_wechat.txt"
                    filepath = os.path.join(OUTPUT_DIR, filename)
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"来源: {url}\n")
                        f.write(f"区县: {district}\n")
                        f.write(f"级别: 初中划片\n")
                        f.write("=" * 60 + "\n\n")
                        f.write(content)
                    print(f"  ✓ {district}: saved {len(content)} chars")
                else:
                    # Take screenshot for debugging
                    screenshot_path = os.path.join(OUTPUT_DIR, f"screenshot_wechat_{district}.png")
                    await page.screenshot(path=screenshot_path)
                    print(f"  ✗ {district}: content too short ({len(content) if content else 0} chars), screenshot saved")
                    
                    # Try getting HTML for analysis
                    html = await page.evaluate('document.documentElement.outerHTML.substring(0, 5000)')
                    debug_path = os.path.join(OUTPUT_DIR, f"debug_wechat_{district}.html")
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"  Debug HTML saved to {debug_path}")
                    
            except Exception as e:
                print(f"  ✗ {district}: {e}")
            finally:
                await page.close()
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

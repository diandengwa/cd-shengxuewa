"""
Full-page screenshot of WeChat articles and OCR them.
"""
import asyncio
import os
from playwright.async_api import async_playwright
from PIL import Image
import pytesseract

URLS = {
    "高新区": "https://mp.weixin.qq.com/s?__biz=Mzk0MTM5MTU3MA==&mid=2247639648&idx=1&sn=bb9261d4a158e6278debdab74ff7156a",
    "龙泉驿区": "https://mp.weixin.qq.com/s?__biz=MzA3ODUwMzIxNA==&mid=2651366061&idx=1&sn=c446f90fdc8b5cde317c63f3ada200c3",
    "郫都区": "https://mp.weixin.qq.com/s?__biz=MzIxNTA0ODI3NA==&mid=2651110290&idx=1&sn=bdf45f6d20e3759db63ad0931611da9a",
}

OUTPUT_DIR = r"D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_初中划片"
SCREENSHOTS_DIR = os.path.join(OUTPUT_DIR, "fullpage_screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel='chrome',
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            viewport={'width': 1200, 'height': 900}
        )
        
        for district, url in URLS.items():
            page = await context.new_page()
            try:
                print(f"\n{'='*60}")
                print(f"Processing {district}...")
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_timeout(5000)
                
                # Scroll down to load all lazy images
                prev_height = 0
                for i in range(20):
                    await page.evaluate('window.scrollBy(0, 500)')
                    await page.wait_for_timeout(800)
                    curr_height = await page.evaluate('document.body.scrollHeight')
                    if curr_height == prev_height:
                        break
                    prev_height = curr_height
                
                # Scroll back to top
                await page.evaluate('window.scrollTo(0, 0)')
                await page.wait_for_timeout(2000)
                
                # Take full-page screenshot
                screenshot_path = os.path.join(SCREENSHOTS_DIR, f"{district}_fullpage.png")
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"  Full-page screenshot: {screenshot_path}")
                
                # OCR the full-page screenshot
                img = Image.open(screenshot_path)
                # Crop to content area (remove WeChat UI elements)
                width, height = img.size
                # Approximate content area - left margin and right margin
                cropped = img.crop((50, 0, width - 50, height))
                
                # OCR with better settings
                text = pytesseract.image_to_string(cropped, lang='chi_sim+eng', config='--psm 3 --oem 3')
                
                # Save OCR result
                ocr_path = os.path.join(OUTPUT_DIR, f"2025_{district}_初中划片_fullpage_ocr.txt")
                with open(ocr_path, "w", encoding="utf-8") as f:
                    f.write(f"区县: {district}\n")
                    f.write(f"级别: 初中划片\n")
                    f.write(f"来源: 微信公众号全页截图OCR\n")
                    f.write(f"注意: OCR可能存在识别错误\n")
                    f.write("=" * 60 + "\n\n")
                    f.write(text)
                
                print(f"  OCR saved: {ocr_path} ({len(text)} chars)")
                
                # Also try extracting text directly from DOM
                dom_text = await page.evaluate("""() => {
                    const jsContent = document.querySelector('#js_content');
                    if (jsContent) {
                        // Get text content
                        return jsContent.innerText;
                    }
                    return document.body.innerText;
                }""")
                
                if dom_text and len(dom_text.strip()) > 50:
                    dom_path = os.path.join(OUTPUT_DIR, f"2025_{district}_初中划片_dom.txt")
                    with open(dom_path, "w", encoding="utf-8") as f:
                        f.write(f"区县: {district}\n")
                        f.write(f"级别: 初中划片\n")
                        f.write(f"来源: 微信公众号DOM提取\n")
                        f.write("=" * 60 + "\n\n")
                        f.write(dom_text)
                    print(f"  DOM text saved: {dom_path} ({len(dom_text)} chars)")
                else:
                    print(f"  DOM text too short: {len(dom_text) if dom_text else 0} chars")
                
            except Exception as e:
                print(f"  ✗ {district}: {e}")
            finally:
                await page.close()
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import json
import os
from playwright.async_api import async_playwright

MISSING_DISTRICTS = [
    ("龙泉驿区", "https://cd.bendibao.com/edu/2025617/198872_11.shtm"),
    ("东部新区", "https://cd.bendibao.com/edu/2025617/198872_22.shtm"),
]

async def try_solve_captcha_v2(page):
    """Try to solve the slider captcha by looking for the drag handle."""
    try:
        await asyncio.sleep(2)
        
        # Try multiple selectors for the slider button
        selectors = [
            '.slider-btn', '.drag-btn', '.verify-btn',
            '[class*="slider"] [class*="btn"]',
            '[class*="drag"]', 'div.slider-btn',
            'span.slider-btn', '.captcha-slider',
            '#captcha_slider', '.slide-verify-slider',
            'div[class*="slide"]', 
        ]
        
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    box = await el.bounding_box()
                    if box:
                        print(f"  Found slider with selector: {sel}")
                        x = box['x'] + box['width'] / 2
                        y = box['y'] + box['height'] / 2
                        await page.mouse.move(x, y)
                        await page.mouse.down()
                        # Move slowly
                        for offset in range(5, 280, 3):
                            await page.mouse.move(x + offset, y + (1 if offset % 2 == 0 else -1), steps=1)
                            await asyncio.sleep(0.015)
                        await page.mouse.up()
                        await asyncio.sleep(3)
                        return True
            except:
                continue
        
        # Try getting all images and dragging any that might be puzzle pieces
        try:
            images = await page.query_selector_all('img')
            for img in images:
                src = await img.get_attribute('src')
                if src and ('puzzle' in src.lower() or 'captcha' in src.lower() or 'verify' in src.lower()):
                    box = await img.bounding_box()
                    if box:
                        print(f"  Found captcha image: {src}")
                        x = box['x'] + box['width'] / 2
                        y = box['y'] + box['height'] / 2
                        await page.mouse.move(x, y)
                        await page.mouse.down()
                        for offset in range(5, 280, 3):
                            await page.mouse.move(x + offset, y, steps=1)
                            await asyncio.sleep(0.015)
                        await page.mouse.up()
                        await asyncio.sleep(3)
                        return True
        except:
            pass
            
        print("  No slider element found to drag")
        return False
    except Exception as e:
        print(f"  Captcha error: {e}")
        return False

async def main():
    results = {}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        
        for district_name, url in MISSING_DISTRICTS:
            page = await context.new_page()
            print(f"\nProcessing: {district_name}")
            
            for attempt in range(5):
                try:
                    print(f"  Attempt {attempt+1}")
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(4)
                    
                    page_text = await page.text_content('body')
                    if page_text and '拼图验证' in page_text:
                        print("  Captcha detected")
                        await try_solve_captcha_v2(page)
                        await asyncio.sleep(4)
                        
                        page_text = await page.text_content('body')
                        if page_text and '拼图验证' in page_text:
                            # Try reloading
                            print("  Still captcha, reloading...")
                            await page.reload()
                            await asyncio.sleep(5)
                            continue
                    
                    # Check content
                    content = await page.evaluate('''() => {
                        const selectors = [
                            '.article-content', '.content', '#content', 
                            '.detail-content', '.news-content', '.text',
                            'article', '.article', '.main-content',
                            '.entry-content', '.post-content'
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.textContent.trim().length > 100) {
                                return el.innerHTML;
                            }
                        }
                        return document.body.innerHTML;
                    }''')
                    
                    if content and len(content) > 200:
                        print(f"  Success! ({len(content)} chars)")
                        results[district_name] = {'url': url, 'content': content}
                        break
                    else:
                        print(f"  Content too short: {len(content) if content else 0}")
                        
                except Exception as e:
                    print(f"  Error: {e}")
                    await asyncio.sleep(2)
            
            if district_name not in results:
                results[district_name] = {'url': url, 'content': None}
                print(f"  FAILED for {district_name}")
            
            await page.close()
        
        await browser.close()
    
    # Load existing results and merge
    output_dir = r'd:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片'
    results_file = os.path.join(output_dir, 'bendibao_raw_extract.json')
    
    if os.path.exists(results_file):
        with open(results_file, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        # Merge new results
        for k, v in results.items():
            if v['content']:
                existing[k] = v
        results = existing
    
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved. Districts with content: {sum(1 for v in results.values() if v['content'])}")

if __name__ == '__main__':
    asyncio.run(main())

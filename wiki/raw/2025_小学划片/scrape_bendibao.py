import asyncio
import json
import os
import re
from playwright.async_api import async_playwright

DISTRICTS = [
    ("双流区", "https://cd.bendibao.com/edu/2025617/198872_8.shtm"),
    ("郫都区", "https://cd.bendibao.com/edu/2025617/198872_9.shtm"),
    ("温江区", "https://cd.bendibao.com/edu/2025617/198872_10.shtm"),
    ("龙泉驿区", "https://cd.bendibao.com/edu/2025617/198872_11.shtm"),
    ("青白江区", "https://cd.bendibao.com/edu/2025617/198872_12.shtm"),
    ("新津区", "https://cd.bendibao.com/edu/2025617/198872_13.shtm"),
    ("新都区", "https://cd.bendibao.com/edu/2025617/198872_21.shtm"),
    ("东部新区", "https://cd.bendibao.com/edu/2025617/198872_22.shtm"),
]

async def try_solve_captcha(page):
    """Try to solve the slider captcha by dragging."""
    try:
        # Wait a moment for captcha to appear
        await asyncio.sleep(2)
        
        # Check if captcha exists
        captcha = await page.query_selector('.slider-btn, .captcha-btn, .verify-btn, [class*="slider"], [class*="captcha"]')
        if not captcha:
            # Try looking for the puzzle piece
            captcha = await page.query_selector('div[class*="puzzle"] img, img[class*="puzzle"]')
        
        if captcha:
            print("  Found captcha element, attempting to solve...")
            box = await captcha.bounding_box()
            if box:
                # Try dragging from left to right
                x = box['x'] + box['width'] / 2
                y = box['y'] + box['height'] / 2
                await page.mouse.move(x, y)
                await page.mouse.down()
                # Move slowly to the right
                for offset in range(10, 300, 5):
                    await page.mouse.move(x + offset, y, steps=1)
                    await asyncio.sleep(0.02)
                await page.mouse.up()
                await asyncio.sleep(2)
                print("  Captcha drag attempted")
            else:
                print("  Could not get captcha bounding box")
        else:
            print("  No captcha element found")
    except Exception as e:
        print(f"  Captcha handling error: {e}")

async def extract_page_content(page, district_name, url, max_retries=3):
    """Navigate to a page and extract content, handling captcha."""
    for attempt in range(max_retries):
        try:
            print(f"\n  Attempt {attempt+1} for {district_name}: {url}")
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)
            
            # Check if we're on a captcha page
            page_text = await page.text_content('body')
            if page_text and '拼图验证' in page_text:
                print("  Captcha detected, trying to solve...")
                await try_solve_captcha(page)
                await asyncio.sleep(3)
                
                # Check again
                page_text = await page.text_content('body')
                if page_text and '拼图验证' in page_text:
                    print("  Still on captcha page after attempt")
                    continue
            
            # Try to get the article content
            content = await page.evaluate('''() => {
                // Try various content selectors common on bendibao
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
                // Fallback: get the body
                return document.body.innerHTML;
            }''')
            
            if content and len(content) > 200:
                print(f"  Successfully extracted content ({len(content)} chars)")
                return content
            else:
                print(f"  Content too short: {len(content) if content else 0} chars")
                
        except Exception as e:
            print(f"  Error: {e}")
    
    return None

async def main():
    results = {}
    
    async with async_playwright() as p:
        # Use Chromium with a realistic viewport
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        
        for district_name, url in DISTRICTS:
            print(f"\n{'='*60}")
            print(f"Processing: {district_name}")
            print(f"{'='*60}")
            
            content = await extract_page_content(page, district_name, url)
            if content:
                results[district_name] = {
                    'url': url,
                    'content': content
                }
            else:
                print(f"  FAILED to extract content for {district_name}")
                results[district_name] = {
                    'url': url,
                    'content': None
                }
        
        await browser.close()
    
    # Save results
    output_dir = r'd:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片'
    os.makedirs(output_dir, exist_ok=True)
    
    results_file = os.path.join(output_dir, 'bendibao_raw_extract.json')
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved to {results_file}")
    print(f"Districts with content: {sum(1 for v in results.values() if v['content'])}")
    print(f"Districts without content: {sum(1 for v in results.values() if not v['content'])}")

if __name__ == '__main__':
    asyncio.run(main())

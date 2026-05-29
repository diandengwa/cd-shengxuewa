import asyncio
import json
import os
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        
        # Try fetching pidu from bendibao main page (not subpage)
        url = "https://cd.bendibao.com/edu/2025617/198865.shtm"
        print(f"Fetching: {url}")
        
        for attempt in range(5):
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(4)
                
                page_text = await page.text_content('body')
                if page_text and '拼图验证' in page_text:
                    print(f"  Attempt {attempt+1}: Captcha detected, retrying...")
                    await asyncio.sleep(3)
                    continue
                
                content = await page.evaluate('''() => {
                    const selectors = [
                        '.article-content', '.content', '#content', 
                        '.detail-content', '.news-content', '.text',
                        'article', '.article', '.main-content'
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
                    
                    output_dir = r'd:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片'
                    filepath = os.path.join(output_dir, 'pidu_raw.html')
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"  Saved to {filepath}")
                    break
                else:
                    print(f"  Attempt {attempt+1}: Content too short")
                    
            except Exception as e:
                print(f"  Attempt {attempt+1}: Error: {e}")
                await asyncio.sleep(2)
        
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())

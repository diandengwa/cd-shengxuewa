import asyncio
import json
import os
from playwright.async_api import async_playwright

URLS = [
    ("郫都区", "https://cd.bendibao.com/edu/2025630/199263.shtm"),
    ("龙泉驿区", "https://m.cd.bendibao.com/edu/199318_10.shtm"),
    ("双流区", "https://m.cd.bendibao.com/edu/199318_11.shtm"),
]

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
        
        for district, url in URLS:
            page = await context.new_page()
            print(f"\nFetching {district}: {url}")
            
            for attempt in range(3):
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(4)
                    
                    page_text = await page.text_content('body')
                    if page_text and '拼图验证' in page_text:
                        print(f"  Attempt {attempt+1}: Captcha, retrying...")
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
                        results[district] = content
                        break
                    else:
                        print(f"  Attempt {attempt+1}: Content too short ({len(content) if content else 0} chars)")
                        
                except Exception as e:
                    print(f"  Attempt {attempt+1}: Error: {e}")
            
            if district not in results:
                results[district] = None
                print(f"  FAILED for {district}")
            
            await page.close()
        
        await browser.close()
    
    output_dir = r'd:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_初中划片'
    os.makedirs(output_dir, exist_ok=True)
    
    results_file = os.path.join(output_dir, 'chuzhong_raw_extract.json')
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    for k, v in results.items():
        print(f"  {k}: {len(v) if v else 0} chars")

if __name__ == '__main__':
    asyncio.run(main())

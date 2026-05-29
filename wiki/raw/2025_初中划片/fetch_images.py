"""
Fetch images from WeChat articles and government pages, then OCR them.
"""
import asyncio
import os
import re
import requests
from playwright.async_api import async_playwright

OUTPUT_DIR = r"D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_初中划片"
IMAGES_DIR = os.path.join(OUTPUT_DIR, "ocr_images")
os.makedirs(IMAGES_DIR, exist_ok=True)

URLS = {
    "武侯区": "https://mp.weixin.qq.com/s?__biz=MzI0MTEyMTI2Mg==&mid=2651242758&idx=1&sn=3b424a7ff7678b03747bed98cce40dc0",
    "高新区": "https://mp.weixin.qq.com/s?__biz=Mzk0MTM5MTU3MA==&mid=2247639648&idx=1&sn=bb9261d4a158e6278debdab74ff7156a",
    "龙泉驿区": "https://mp.weixin.qq.com/s?__biz=MzA3ODUwMzIxNA==&mid=2651366061&idx=1&sn=c446f90fdc8b5cde317c63f3ada200c3",
    "双流区": "https://mp.weixin.qq.com/s?__biz=MzAwMjI1NTkzMw==&mid=2652208102&idx=1&sn=4093a655d0b34f200bbf2b7a04166324",
    "郫都区": "https://mp.weixin.qq.com/s?__biz=MzIxNTA0ODI3NA==&mid=2651110290&idx=1&sn=bdf45f6d20e3759db63ad0931611da9a",
}

# Also try government URLs
GOV_URLS = {
    "武侯区_gov": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_749d1ae700e94d9db261abacb8fafb2b.shtml",
    "高新区_gov": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_aff212e71101404a9470a830eedb5d2d.shtml",
    "龙泉驿区_gov": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_b40a4fffbcf8463493e25432bf19ee80.shtml",
    "双流区_gov": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_dce92dbae0554e5596451b4837ddc9bc.shtml",
    "郫都区_gov": "https://edu.chengdu.gov.cn/cdedu/c131244/2025-07/01/content_7167efcc82c0475eaf4587d6b67c5cc3.shtml",
}

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
        
        all_results = {}
        
        for district, url in URLS.items():
            page = await context.new_page()
            try:
                print(f"\n{'='*60}")
                print(f"Fetching {district} from WeChat...")
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_timeout(5000)
                
                # Scroll down to load lazy images
                for i in range(5):
                    await page.evaluate(f'window.scrollBy(0, {500 * (i+1)})')
                    await page.wait_for_timeout(1000)
                await page.evaluate('window.scrollTo(0, 0)')
                await page.wait_for_timeout(2000)
                
                # Extract all image URLs from the article
                images = await page.evaluate("""() => {
                    const imgs = [];
                    // WeChat article images
                    document.querySelectorAll('img').forEach(img => {
                        const src = img.getAttribute('data-src') || img.getAttribute('src') || '';
                        const width = img.naturalWidth || img.width || 0;
                        const height = img.naturalHeight || img.height || 0;
                        if (src && (width > 100 || height > 100) && !src.includes('emoji') && !src.includes('qrcode')) {
                            imgs.push({src, width, height});
                        }
                    });
                    return imgs;
                }""")
                
                # Also get text content
                text = await page.evaluate("""() => {
                    const jsContent = document.querySelector('#js_content');
                    if (jsContent) return jsContent.innerText;
                    return document.body.innerText;
                }""")
                
                print(f"  Found {len(images)} images, text length: {len(text) if text else 0}")
                
                # Download images
                downloaded = []
                for i, img in enumerate(images):
                    src = img['src']
                    if src.startswith('//'):
                        src = 'https:' + src
                    try:
                        ext = 'jpg'
                        if 'png' in src.lower():
                            ext = 'png'
                        filename = f"{district}_wechat_{i+1}.{ext}"
                        filepath = os.path.join(IMAGES_DIR, filename)
                        
                        resp = requests.get(src, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Referer': 'https://mp.weixin.qq.com/'
                        }, timeout=15)
                        if resp.status_code == 200 and len(resp.content) > 5000:
                            with open(filepath, 'wb') as f:
                                f.write(resp.content)
                            downloaded.append(filename)
                            print(f"  ✓ Downloaded: {filename} ({len(resp.content)} bytes)")
                        else:
                            print(f"  ✗ Skip: {src[:80]} (status={resp.status_code}, size={len(resp.content)})")
                    except Exception as e:
                        print(f"  ✗ Error downloading image {i+1}: {e}")
                
                all_results[district] = {
                    'images': downloaded,
                    'text_length': len(text) if text else 0,
                    'text_preview': text[:500] if text else ''
                }
                
            except Exception as e:
                print(f"  ✗ {district}: {e}")
                all_results[district] = {'error': str(e)}
            finally:
                await page.close()
        
        await browser.close()
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY:")
        for district, result in all_results.items():
            if 'error' in result:
                print(f"  {district}: ERROR - {result['error']}")
            else:
                print(f"  {district}: {len(result['images'])} images downloaded, text={result['text_length']} chars")

if __name__ == "__main__":
    asyncio.run(main())

"""
微信公众号草稿封面图上传脚本 v2

使用 CDP 协议直接操作 Chrome，为指定草稿上传封面图。

策略:
  1. 从已有的公众号页面获取 token
  2. 直接导航到草稿编辑页面 (appmsg_edit)
  3. 在编辑页面上传封面图
  4. 保存草稿

使用方式:
    python upload_cover_v2.py --media-id <草稿media_id> --cover <封面图路径> [--screenshot-dir <截图目录>]
"""

import argparse
import json
import os
import sys
import time
import base64
import asyncio
import re
import urllib.request

CDP_PORT = 9222
CDP_HOST = "127.0.0.1"


class CDPClient:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.msg_id = 0

    async def send(self, method, params=None, timeout=30):
        import websockets
        async with websockets.connect(self.ws_url, max_size=50*1024*1024) as ws:
            self.msg_id += 1
            msg = {"id": self.msg_id, "method": method, "params": params or {}}
            await ws.send(json.dumps(msg))
            deadline = time.time() + timeout
            while time.time() < deadline:
                remaining = deadline - time.time()
                response = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 30))
                data = json.loads(response)
                if data.get("id") == self.msg_id:
                    return data
            return {"error": "timeout"}

    async def evaluate(self, expression, timeout=15):
        return await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True
        }, timeout=timeout)

    async def eval_value(self, expression, timeout=15):
        result = await self.evaluate(expression, timeout)
        return result.get("result", {}).get("result", {}).get("value")

    async def wait_for_page(self, timeout=15):
        for _ in range(timeout * 4):
            val = await self.eval_value("document.readyState")
            if val == "complete":
                return True
            await asyncio.sleep(0.25)
        return False

    async def navigate(self, url, wait=3):
        await self.send("Page.navigate", {"url": url})
        await asyncio.sleep(wait)
        await self.wait_for_page(10)
        await asyncio.sleep(2)

    async def screenshot(self, output_path):
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        data = result.get("result", {}).get("data", "")
        if data:
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(data))
            print(f"  screenshot: {output_path}")
        return bool(data)

    async def get_token(self):
        url = await self.eval_value("window.location.href")
        if url:
            match = re.search(r'token=(\d+)', url)
            if match:
                return match.group(1)
        token = await self.eval_value("""
            (function() {
                const links = document.querySelectorAll('a[href*="token="]');
                for (const a of links) {
                    const m = a.href.match(/token=(\\\\d+)/);
                    if (m) return m[1];
                }
                return null;
            })()
        """)
        if token:
            return token
        token = await self.eval_value("""
            (function() {
                const scripts = document.querySelectorAll('script');
                for (const s of scripts) {
                    const m = s.textContent.match(/token['"\\\\s]*[:=]['"\\\\s]*(\\\\d+)/);
                    if (m) return m[1];
                }
                return null;
            })()
        """)
        return token


def get_tabs():
    url = f"http://{CDP_HOST}:{CDP_PORT}/json/list"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode())


async def upload_cover(media_id, cover_path, screenshot_dir=""):
    abs_cover = os.path.abspath(cover_path).replace("/", "\\")
    if not os.path.exists(abs_cover):
        print(f"Cover image not found: {abs_cover}")
        return False

    try:
        tabs = get_tabs()
    except Exception as e:
        print(f"Cannot connect to Chrome CDP: {e}")
        return False

    wechat_tab = None
    for tab in tabs:
        if "mp.weixin.qq.com" in tab.get("url", ""):
            wechat_tab = tab
            break

    if not wechat_tab:
        print("No WeChat MP tab found")
        return False

    ws_url = wechat_tab.get("webSocketDebuggerUrl", "")
    if not ws_url:
        print("Cannot get WebSocket URL")
        return False

    client = CDPClient(ws_url)
    print(f"Connected tab: {wechat_tab.get('title', '?')}")

    # Step 1: Get token
    print("\n--- Step 1: Get token ---")
    token = await client.get_token()
    if not token:
        print("Cannot get token")
        if screenshot_dir:
            os.makedirs(screenshot_dir, exist_ok=True)
            await client.screenshot(os.path.join(screenshot_dir, "step1_no_token.png"))
        return False
    print(f"  token: {token[:6]}...{token[-4:]}")

    # Step 2: Navigate to draft edit page
    print(f"\n--- Step 2: Navigate to draft edit (media_id={media_id}) ---")
    edit_url = (
        f"https://mp.weixin.qq.com/cgi-bin/appmsg"
        f"?t=media/appmsg_edit&action=edit&type=77"
        f"&appmsgid={media_id}&token={token}"
    )
    await client.navigate(edit_url, wait=5)

    if screenshot_dir:
        os.makedirs(screenshot_dir, exist_ok=True)
        await client.screenshot(os.path.join(screenshot_dir, f"step2_edit_{media_id}.png"))

    page_title = await client.eval_value("document.title")
    page_url = await client.eval_value("window.location.href")
    print(f"  title: {page_title}")
    print(f"  url: {page_url[:120]}")

    if "login" in (page_url or "").lower():
        print("Redirected to login page")
        return False

    # Step 3: Wait for editor to fully load
    print("\n--- Step 3: Wait for editor ---")
    await asyncio.sleep(5)

    # Explore DOM - find file inputs and cover elements
    dom_info = await client.eval_value("""
        (function() {
            var info = {file_inputs: [], cover_hits: [], iframes: []};
            document.querySelectorAll('input[type="file"]').forEach(function(inp) {
                info.file_inputs.push({
                    id: inp.id, name: inp.name, className: inp.className,
                    accept: inp.accept, visible: inp.offsetParent !== null
                });
            });
            var sels = [
                '.media_cover_picker', '.js-cover-area', '.cover-area',
                '[data-type="cover"]', '.cover_inner', '.js_cover',
                '#js_cover', '.icon_cover', '.weui-desktop-form__cell_cover',
                '.card_cover', '.appmsg_cover'
            ];
            for (var i = 0; i < sels.length; i++) {
                var el = document.querySelector(sels[i]);
                if (el) info.cover_hits.push({sel: sels[i], cls: el.className});
            }
            document.querySelectorAll('iframe').forEach(function(fr) {
                info.iframes.push({src: (fr.src||'').substring(0,100), id: fr.id});
            });
            return JSON.stringify(info);
        })()
    """)
    print(f"  DOM info: {dom_info}")

    try:
        info = json.loads(dom_info) if dom_info else {}
    except Exception:
        info = {}

    file_inputs = info.get("file_inputs", [])
    cover_hits = info.get("cover_hits", [])
    iframes = info.get("iframes", [])

    print(f"  file inputs: {len(file_inputs)}")
    for fi in file_inputs:
        print(f"    id={fi.get('id')} name={fi.get('name')} accept={fi.get('accept')} vis={fi.get('visible')}")
    print(f"  cover hits: {len(cover_hits)}")
    for ch in cover_hits:
        print(f"    {ch.get('sel')} -> {ch.get('cls')}")
    print(f"  iframes: {len(iframes)}")
    for fr in iframes:
        print(f"    id={fr.get('id')} src={fr.get('src')}")

    # Step 4: Upload cover image
    print("\n--- Step 4: Upload cover image ---")

    # Strategy A: If there are file inputs, try to click cover area then set file
    if file_inputs:
        # First try clicking the cover area to trigger file input visibility
        click_result = await client.eval_value("""
            (function() {
                var sels = [
                    '.media_cover_picker', '.js-cover-area', '.cover-area',
                    '.cover_inner', '.js_cover', '#js_cover', '.icon_cover'
                ];
                for (var i = 0; i < sels.length; i++) {
                    var el = document.querySelector(sels[i]);
                    if (el) { el.click(); return 'clicked: ' + sels[i]; }
                }
                var all = document.querySelectorAll('div, span, a, label, button');
                for (var j = 0; j < all.length; j++) {
                    var t = all[j].textContent.trim();
                    if (t === '封面' || t === '选择封面' || t.indexOf('上传封面') >= 0) {
                        if (all[j].offsetParent !== null) { all[j].click(); return 'clicked_text: ' + t; }
                    }
                }
                return 'no_cover_clicked';
            })()
        """)
        print(f"  click cover area: {click_result}")
        await asyncio.sleep(1)

    # Use DOM.setFileInputFiles to upload
    # Get backend node id for file input
    doc_result = await client.send("DOM.getDocument", {"depth": 0})
    root_node_id = doc_result.get("result", {}).get("root", {}).get("nodeId", 0)
    print(f"  DOM root nodeId: {root_node_id}")

    # Try to find file input in main document
    query_result = await client.send("DOM.querySelector", {
        "nodeId": root_node_id,
        "selector": 'input[type="file"]'
    })
    file_node_id = query_result.get("result", {}).get("nodeId", 0)
    print(f"  file input nodeId: {file_node_id}")

    if file_node_id:
        set_result = await client.set_file_input(abs_cover, file_node_id)
        if "error" in set_result:
            print(f"  set file error: {set_result.get('error')}")
        else:
            print(f"  file set successfully!")
            await asyncio.sleep(3)  # Wait for upload

            if screenshot_dir:
                await client.screenshot(os.path.join(screenshot_dir, f"step4_after_upload_{media_id}.png"))

            # Step 5: Save draft
            print("\n--- Step 5: Save draft ---")
            save_result = await client.eval_value("""
                (function() {
                    var btns = document.querySelectorAll('button, a.weui-desktop-btn, .weui-desktop-btn_primary');
                    for (var i = 0; i < btns.length; i++) {
                        var t = btns[i].textContent.trim();
                        if (t.indexOf('保存') >= 0 || t.indexOf('确定') >= 0) {
                            btns[i].click();
                            return 'clicked_save: ' + t;
                        }
                    }
                    return 'save_btn_not_found';
                })()
            """)
            print(f"  save result: {save_result}")
            await asyncio.sleep(2)

            if screenshot_dir:
                await client.screenshot(os.path.join(screenshot_dir, f"step5_after_save_{media_id}.png"))

            return True
    else:
        print("  No file input found in main document")

        # Check if editor is in an iframe
        if iframes:
            print("  Trying iframes...")
            for i, fr in enumerate(iframes):
                try:
                    # Try to query file input in iframe context
                    iframe_query = await client.eval_value(f"""
                        (function() {{
                            var frames = document.querySelectorAll('iframe');
                            if (frames[{i}] && frames[{i}].contentDocument) {{
                                var inp = frames[{i}].contentDocument.querySelector('input[type="file"]');
                                if (inp) return inp.id || inp.name || 'found';
                            }}
                            return 'no_file_input_in_iframe_{i}';
                        }})()
                    """)
                    print(f"  iframe[{i}] file input: {iframe_query}")
                except Exception as e:
                    print(f"  iframe[{i}] error: {e}")

        # Alternative: try using Page.getFrameTree to find iframe contexts
        frame_tree = await client.send("Page.getFrameTree")
        frames = frame_tree.get("result", {}).get("frameTree", {}).get("childFrames", [])
        print(f"\n  Found {len(frames)} child frames")
        for fr in frames:
            frame_info = fr.get("frame", {})
            print(f"    frame id={frame_info.get('id')} url={frame_info.get('url','')[:80]}")

        if screenshot_dir:
            await client.screenshot(os.path.join(screenshot_dir, f"step4_no_file_input_{media_id}.png"))

        return False


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-id", required=True)
    parser.add_argument("--cover", required=True)
    parser.add_argument("--screenshot-dir", default="")
    args = parser.parse_args()

    result = await upload_cover(args.media_id, args.cover, args.screenshot_dir)
    if result:
        print("\n✅ Cover image uploaded successfully!")
    else:
        print("\n❌ Cover image upload failed")
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    asyncio.run(main())

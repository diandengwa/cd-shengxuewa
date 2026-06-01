"""
微信公众号草稿封面图上传脚本 v3

通过 CDP 协议操作 Chrome，为指定草稿上传封面图。

核心修复:
  - 用 Runtime.evaluate + DOM.requestNode 获取 backendNodeId
    (DOM.querySelector 在 depth=0 时无法查询子节点)
  - 等待页面完全加载后再操作
  - 支持通过 Chrome profile 复用已登录 session

使用方式:
    python upload_cover_v3.py --media-id <media_id> --cover <封面图路径>
"""

import argparse
import json
import os
import sys
import time
import asyncio
import re
import base64
import urllib.request

CDP_PORT = 9222
CDP_HOST = "127.0.0.1"


class CDPClient:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.msg_id = 0

    async def send(self, method, params=None, timeout=30):
        import websockets
        async with websockets.connect(self.ws_url, max_size=50 * 1024 * 1024) as ws:
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
            return {"error": "timeout", "method": method}

    async def evaluate(self, expression, timeout=15):
        return await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True
        }, timeout=timeout)

    async def eval_value(self, expression, timeout=15):
        result = await self.evaluate(expression, timeout)
        return result.get("result", {}).get("result", {}).get("value")

    async def wait_for_page(self, timeout=20):
        """Wait for page to finish loading"""
        for _ in range(timeout * 4):
            val = await self.eval_value("document.readyState")
            if val == "complete":
                return True
            await asyncio.sleep(0.25)
        return False

    async def navigate(self, url, wait_after_nav=5):
        await self.send("Page.navigate", {"url": url})
        await asyncio.sleep(2)
        await self.wait_for_page(15)
        await asyncio.sleep(wait_after_nav)

    async def screenshot(self, output_path):
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        data = result.get("result", {}).get("data", "")
        if data:
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(data))
            print(f"  screenshot saved: {output_path}")
        return bool(data)

    async def get_token(self):
        """Extract token from page URL or content"""
        # Method 1: from current URL
        url = await self.eval_value("window.location.href")
        if url:
            m = re.search(r'token=(\d+)', url)
            if m:
                return m.group(1)
        # Method 2: from all links in page
        token = await self.eval_value("""
            (function(){
                var links = document.querySelectorAll('a[href*="token="]');
                for(var i=0;i<links.length;i++){
                    var m = links[i].href.match(/token=(\\d+)/);
                    if(m) return m[1];
                }
                return null;
            })()
        """)
        if token:
            return token
        # Method 3: from window.__token__ or similar global
        token = await self.eval_value("window.__token__ || window._token || ''")
        if token:
            return token
        return None

    async def get_element_backend_node_id(self, js_expression):
        """
        Get backendNodeId for an element returned by JS expression.
        Uses Runtime.evaluate (returnObject=true) + DOM.requestNode.
        """
        # Evaluate and get objectId
        eval_result = await self.send("Runtime.evaluate", {
            "expression": js_expression,
            "returnByValue": False,
        })
        obj_id = eval_result.get("result", {}).get("objectId", "")
        if not obj_id:
            return 0
        # Request backend node id
        req_result = await self.send("DOM.requestNode", {
            "objectId": obj_id
        })
        return req_result.get("result", {}).get("nodeId", 0)

    async def set_file_input_by_js(self, file_path, js_expression):
        """
        Set file on an input[type=file] element via JS expression.
        Returns (success, backend_node_id)
        """
        node_id = await self.get_element_backend_node_id(js_expression)
        if not node_id:
            return False, 0
        result = await self.send("DOM.setFileInputFiles", {
            "files": [file_path],
            "nodeId": node_id
        })
        if "error" in result:
            print(f"  setFileInputFiles error: {result['error']}")
            return False, node_id
        return True, node_id


def get_tabs():
    url = f"http://{CDP_HOST}:{CDP_PORT}/json/list"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode())


async def upload_cover(media_id, cover_path, screenshot_dir=""):
    abs_cover = os.path.abspath(cover_path).replace("/", "\\")
    if not os.path.exists(abs_cover):
        print(f"ERROR: cover image not found: {abs_cover}")
        return False

    try:
        tabs = get_tabs()
    except Exception as e:
        print(f"ERROR: cannot connect to Chrome CDP: {e}")
        return False

    wechat_tab = None
    for tab in tabs:
        if "mp.weixin.qq.com" in tab.get("url", ""):
            wechat_tab = tab
            break

    if not wechat_tab:
        print("ERROR: no WeChat MP tab found. Please open mp.weixin.qq.com in Chrome.")
        return False

    ws_url = wechat_tab.get("webSocketDebuggerUrl", "")
    if not ws_url:
        print("ERROR: no WebSocket URL")
        return False

    client = CDPClient(ws_url)
    print(f"Connected to tab: {wechat_tab.get('title', '?')[:50]}")

    # =====================================================
    # Step 1: Get token from current page
    # =====================================================
    print("\n--- Step 1: Get token ---")
    token = await client.get_token()
    if not token:
        print("ERROR: cannot get token. Please make sure you are logged in to mp.weixin.qq.com")
        if screenshot_dir:
            os.makedirs(screenshot_dir, exist_ok=True)
            await client.screenshot(os.path.join(screenshot_dir, "step1_no_token.png"))
        return False
    print(f"  token = {token[:8]}...{token[-4:]}  (len={len(token)})")

    # =====================================================
    # Step 2: Navigate to draft edit page
    # =====================================================
    print(f"\n--- Step 2: Navigate to draft edit page (media_id={media_id}) ---")
    edit_url = (
        f"https://mp.weixin.qq.com/cgi-bin/appmsg"
        f"?t=media/appmsg_edit&action=edit&type=77"
        f"&appmsgid={media_id}&token={token}"
    )
    print(f"  URL: {edit_url[:120]}...")
    await client.navigate(edit_url, wait_after_nav=6)

    if screenshot_dir:
        os.makedirs(screenshot_dir, exist_ok=True)
        await client.screenshot(os.path.join(screenshot_dir, f"step2_loaded_{media_id}.png"))

    page_title = await client.eval_value("document.title")
    page_url = await client.eval_value("window.location.href")
    print(f"  title: {page_title}")
    print(f"  url:   {page_url[:120]}")

    if "login" in (page_url or "").lower() or "扫码" in (page_title or ""):
        print("ERROR: redirected to login page. Please login first.")
        return False

    # =====================================================
    # Step 3: Wait for editor to fully initialize
    # =====================================================
    print("\n--- Step 3: Wait for editor + explore DOM ---")
    await asyncio.sleep(5)

    # Explore: count file inputs and cover-related elements
    dom_summary = await client.eval_value("""
        (function(){
            var summary = {
                fileInputCount: document.querySelectorAll('input[type="file"]').length,
                bodyHasCover: document.body.innerHTML.indexOf('封面') >= 0,
                iframes: [],
                buttons: []
            };
            document.querySelectorAll('iframe').forEach(function(fr){
                summary.iframes.push({id: fr.id, src: (fr.src||'').substring(0,80)});
            });
            document.querySelectorAll('button, .weui-desktop-btn, .weui-desktop-btn_primary').forEach(function(b){
                var t = b.textContent.trim();
                if(t && t.length < 20) summary.buttons.push(t);
            });
            return JSON.stringify(summary);
        })()
    """)
    print(f"  DOM summary: {dom_summary}")
    try:
        dom = json.loads(dom_summary) if dom_summary else {}
    except Exception:
        dom = {}

    file_input_count = dom.get("fileInputCount", 0)
    print(f"  file inputs on page: {file_input_count}")

    # =====================================================
    # Step 4: Upload cover image
    # =====================================================
    print("\n--- Step 4: Upload cover image ---")

    if file_input_count == 0:
        print("  No file input found on page. The editor might use a different upload mechanism.")
        print("  Trying to find upload button / cover area...")

        # Try clicking various "upload cover" triggers
        click_result = await client.eval_value("""
            (function(){
                // Look for elements with '封面' text
                var all = document.querySelectorAll('*');
                for(var i=0;i<all.length;i++){
                    var t = all[i].textContent.trim();
                    if((t==='封面'||t==='上传封面'||t.indexOf('封　　面')>=0) && all[i].offsetParent!==null){
                        all[i].click();
                        return 'clicked:'+t+' on '+all[i].tagName;
                    }
                }
                // Try common cover area selectors for WeChat MP
                var sels = ['.cover-area','.js-cover-area','.media_cover_picker','.cover_inner','#js_cover','.js_cover'];
                for(var j=0;j<sels.length;j++){
                    var el = document.querySelector(sels[j]);
                    if(el){ el.click(); return 'clicked_selector:'+sels[j]; }
                }
                return 'not_found';
            })()
        """)
        print(f"  click result: {click_result}")
        await asyncio.sleep(2)

        # Re-check file inputs after clicking
        file_input_count = await client.eval_value("document.querySelectorAll('input[type=\"file\"]').length")
        print(f"  file inputs after click: {file_input_count}")

    if file_input_count == 0:
        print("ERROR: still no file input found. Cannot upload cover image.")
        if screenshot_dir:
            await client.screenshot(os.path.join(screenshot_dir, f"step4_no_file_input_{media_id}.png"))
        return False

    # Now upload the file using DOM.setFileInputFiles
    # We use Runtime.evaluate to get the element, then DOM.requestNode to get backendNodeId
    print(f"  Uploading file: {abs_cover}")

    # Try the first file input found by JS
    success, node_id = await client.set_file_input_by_js(
        abs_cover,
        "document.querySelectorAll('input[type=\"file\"]')[0]"
    )

    if not success:
        # Try all file inputs
        print("  First file input failed, trying all file inputs...")
        for i in range(file_input_count):
            success, node_id = await client.set_file_input_by_js(
                abs_cover,
                f"document.querySelectorAll('input[type=\"file\"]')[{i}]"
            )
            if success:
                print(f"  Success with file input [{i}] (nodeId={node_id})")
                break

    if not success:
        print("ERROR: DOM.setFileInputFiles failed for all file inputs")
        if screenshot_dir:
            await client.screenshot(os.path.join(screenshot_dir, f"step4_upload_failed_{media_id}.png"))
        return False

    print("  File set successfully! Waiting for WeChat to process upload...")
    await asyncio.sleep(5)  # Wait for upload to complete

    if screenshot_dir:
        await client.screenshot(os.path.join(screenshot_dir, f"step4_after_upload_{media_id}.png"))

    # Verify upload succeeded (check if cover preview appears)
    cover_uploaded = await client.eval_value("""
        (function(){
            // Check if cover preview image appeared
            var imgs = document.querySelectorAll('.cover-area img, .js-cover-area img, .media_cover_picker img, .cover_inner img');
            if(imgs.length > 0) return 'preview_imgs:' + imgs.length;
            // Check if upload success text appears
            var body = document.body.innerText;
            if(body.indexOf('上传成功')>=0) return 'upload_success_text';
            return 'unknown';
        })()
    """)
    print(f"  Upload verification: {cover_uploaded}")

    # =====================================================
    # Step 5: Save draft
    # =====================================================
    print("\n--- Step 5: Save draft ---")
    save_result = await client.eval_value("""
        (function(){
            var btns = document.querySelectorAll('button, a.weui-desktop-btn, a.weui-desktop-btn_primary, .weui-desktop-btn_primary');
            for(var i=0;i<btns.length;i++){
                var t = btns[i].textContent.trim();
                if(t==='保存' || t.indexOf('保 存')>=0 || t==='确定'){
                    btns[i].click();
                    return 'clicked:'+t;
                }
            }
            return 'save_btn_not_found';
        })()
    """)
    print(f"  Save result: {save_result}")
    await asyncio.sleep(2)

    if screenshot_dir:
        await client.screenshot(os.path.join(screenshot_dir, f"step5_after_save_{media_id}.png"))

    print("\n✅ Cover image upload flow completed!")
    return True


async def main():
    parser = argparse.ArgumentParser(description="Upload cover image to WeChat MP draft via CDP")
    parser.add_argument("--media-id", required=True, help="Draft media_id")
    parser.add_argument("--cover", required=True, help="Cover image file path")
    parser.add_argument("--screenshot-dir", default="D:/opc/pipeline-logs", help="Screenshot directory")
    args = parser.parse_args()

    result = await upload_cover(args.media_id, args.cover, args.screenshot_dir)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    asyncio.run(main())

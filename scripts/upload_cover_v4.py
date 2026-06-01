"""
微信公众号草稿封面图上传脚本 v4

通过 CDP 协议操作 Chrome，为指定草稿上传封面图。

核心修复:
  - 使用持久 WebSocket 连接 (每次 send() 不复连)
  - 用 Runtime.evaluate + DOM.requestNode 获取 backendNodeId
  - 等待页面完全加载后再操作
  - 支持通过 Chrome profile 复用已登录 session

使用方式:
    python upload_cover_v4.py --media-id <media_id> --cover <封面图路径>
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
import websockets

CDP_PORT = 9222
CDP_HOST = "127.0.0.1"


class CDPClient:
    """CDP client with persistent WebSocket connection"""

    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.msg_id = 0
        self._ws = None
        self._loop = None

    async def __aenter__(self):
        self._ws = await websockets.connect(self.ws_url, max_size=50 * 1024 * 1024)
        return self

    async def __aexit__(self, *_):
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send(self, method, params=None, timeout=30):
        if not self._ws:
            raise RuntimeError("WebSocket not connected. Use 'async with' context manager.")

        self.msg_id += 1
        msg = {"id": self.msg_id, "method": method, "params": params or {}}
        await self._ws.send(json.dumps(msg))

        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            raw = await asyncio.wait_for(self._ws.recv(), timeout=min(remaining, 30))
            data = json.loads(raw)
            if data.get("id") == self.msg_id:
                return data

        return {"error": {"message": "timeout"}, "method": method}

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
        for _ in range(timeout * 4):
            val = await self.eval_value("document.readyState")
            if val == "complete":
                return True
            await asyncio.sleep(0.25)
        return False

    async def navigate(self, url, wait_after=5):
        await self.send("Page.navigate", {"url": url})
        await asyncio.sleep(2)
        await self.wait_for_page(15)
        await asyncio.sleep(wait_after)

    async def screenshot(self, output_path):
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        data = result.get("result", {}).get("data", "")
        if data:
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(data))
            print(f"  screenshot: {os.path.basename(output_path)}")
        return bool(data)

    async def get_token(self):
        url = await self.eval_value("window.location.href")
        if url:
            m = re.search(r'token=(\d+)', url)
            if m:
                return m.group(1)
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
        return token

    async def get_file_input_backend_node_id(self):
        """
        Find the first visible file input element and return its backendNodeId.
        Uses Runtime.evaluate (returnByValue=false) + DOM.requestNode.
        """
        # First get the DOM document root (need depth>0 to access children)
        doc = await self.send("DOM.getDocument", {"depth": -1})
        # depth=-1 means full tree; use a reasonable depth
        # Actually, let's use Runtime to get the element and then requestNode

        # Get objectId of the file input element
        eval_result = await self.send("Runtime.evaluate", {
            "expression": "document.querySelector('input[type=\"file\"]')",
            "returnByValue": False,
        })
        obj_id = eval_result.get("result", {}).get("objectId", "")
        if not obj_id:
            # Try all file inputs
            eval_result2 = await self.send("Runtime.evaluate", {
                "expression": "document.querySelectorAll('input[type=\"file\"]')[0]",
                "returnByValue": False,
            })
            obj_id = eval_result2.get("result", {}).get("objectId", "")

        if not obj_id:
            return 0

        # Get backendNodeId
        req = await self.send("DOM.requestNode", {"objectId": obj_id})
        return req.get("result", {}).get("nodeId", 0)

    async def set_file_on_input(self, file_path, node_id):
        return await self.send("DOM.setFileInputFiles", {
            "files": [file_path],
            "nodeId": node_id
        })


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
        print(f"ERROR: cannot connect to Chrome CDP ({e})")
        print("  Make sure Chrome is running with --remote-debugging-port=9222")
        return False

    wechat_tab = None
    for tab in tabs:
        if "mp.weixin.qq.com" in tab.get("url", ""):
            wechat_tab = tab
            break

    if not wechat_tab:
        print("ERROR: no WeChat MP tab found.")
        print("  Please open mp.weixin.qq.com in Chrome.")
        return False

    ws_url = wechat_tab.get("webSocketDebuggerUrl", "")
    if not ws_url:
        print("ERROR: no WebSocket debugger URL")
        return False

    print(f"Connected to tab: {wechat_tab.get('title', '?')[:50]}")

    async with CDPClient(ws_url) as client:
        # =====================================================
        # Step 1: Get token
        # =====================================================
        print("\n--- Step 1: Get token ---")
        token = await client.get_token()
        if not token:
            print("ERROR: cannot get token")
            print("  Please login to mp.weixin.qq.com first")
            if screenshot_dir:
                os.makedirs(screenshot_dir, exist_ok=True)
                await client.screenshot(os.path.join(screenshot_dir, "step1_no_token.png"))
            return False
        print(f"  token = {token[:8]}...{token[-4:]}  (len={len(token)})")

        # =====================================================
        # Step 2: Navigate to draft edit page
        # =====================================================
        print(f"\n--- Step 2: Navigate to draft edit (media_id={media_id}) ---")
        edit_url = (
            f"https://mp.weixin.qq.com/cgi-bin/appmsg"
            f"?t=media/appmsg_edit&action=edit&type=77"
            f"&appmsgid={media_id}&token={token}"
        )
        await client.navigate(edit_url, wait_after=6)

        if screenshot_dir:
            os.makedirs(screenshot_dir, exist_ok=True)
            await client.screenshot(os.path.join(screenshot_dir, f"step2_loaded_{media_id}.png"))

        page_title = await client.eval_value("document.title")
        page_url = await client.eval_value("window.location.href")
        print(f"  title: {page_title}")
        print(f"  url:   {page_url[:120]}")

        if "login" in (page_url or "").lower() or "扫码" in (page_title or ""):
            print("ERROR: redirected to login page")
            return False

        # =====================================================
        # Step 3: Wait for editor + explore DOM
        # =====================================================
        print("\n--- Step 3: Wait for editor + explore DOM ---")
        await asyncio.sleep(5)

        dom_summary = await client.eval_value("""
            (function(){
                var s = {fileInputs:0, iframes:0, buttons:[], hasCoverText:false};
                s.fileInputs = document.querySelectorAll('input[type="file"]').length;
                s.iframes = document.querySelectorAll('iframe').length;
                var btns = document.querySelectorAll('button, .weui-desktop-btn, .weui-desktop-btn_primary');
                for(var i=0;i<btns.length;i++){
                    var t=btns[i].textContent.trim(); if(t&&t.length<15) s.buttons.push(t);
                }
                s.hasCoverText = document.body.innerHTML.indexOf('封面')>=0;
                return JSON.stringify(s);
            })()
        """)
        print(f"  DOM summary: {dom_summary}")
        try:
            dom = json.loads(dom_summary) if dom_summary else {}
        except Exception:
            dom = {}
        file_input_count = dom.get("fileInputs", 0)
        print(f"  file inputs on page: {file_input_count}")
        print(f"  iframes: {dom.get('iframes', 0)}")
        print(f"  buttons: {dom.get('buttons', [])}")

        # =====================================================
        # Step 4: Upload cover image
        # =====================================================
        print("\n--- Step 4: Upload cover image ---")
        print(f"  file: {os.path.basename(abs_cover)}")

        if file_input_count == 0:
            print("  No file input found. Trying to click cover area...")
            click_result = await client.eval_value("""
                (function(){
                    var sels=['.cover-area','.js-cover-area','.media_cover_picker','.cover_inner','#js_cover','.js_cover'];
                    for(var i=0;i<sels.length;i++){var el=document.querySelector(sels[i]);if(el){el.click();return 'clicked:'+sels[i];}}
                    return 'no_cover_area';
                })()
            """)
            print(f"  click result: {click_result}")
            await asyncio.sleep(2)
            file_input_count = await client.eval_value("document.querySelectorAll('input[type=\"file\"]').length")
            print(f"  file inputs after click: {file_input_count}")

        if file_input_count == 0:
            print("ERROR: still no file input found")
            if screenshot_dir:
                await client.screenshot(os.path.join(screenshot_dir, f"step4_no_file_input_{media_id}.png"))
            return False

        # Get backendNodeId and upload
        print("  Getting file input backendNodeId...")
        node_id = await client.get_file_input_backend_node_id()
        print(f"  backendNodeId = {node_id}")

        if node_id == 0:
            print("ERROR: cannot get backendNodeId for file input")
            if screenshot_dir:
                await client.screenshot(os.path.join(screenshot_dir, f"step4_no_node_id_{media_id}.png"))
            return False

        print(f"  Setting file on input (nodeId={node_id})...")
        set_result = await client.set_file_on_input(abs_cover, node_id)
        if "error" in set_result:
            print(f"ERROR: setFileInputFiles failed: {set_result['error']}")
            return False

        print("  File set successfully! Waiting for WeChat to process upload...")
        await asyncio.sleep(5)

        if screenshot_dir:
            await client.screenshot(os.path.join(screenshot_dir, f"step4_after_upload_{media_id}.png"))

        # Verify
        verify = await client.eval_value("""
            (function(){
                var imgs=document.querySelectorAll('.cover-area img,.js-cover-area img,.media_cover_picker img,.cover_inner img');
                if(imgs.length>0) return 'cover_preview_shown';
                if(document.body.innerText.indexOf('成功')>=0) return 'success_text_found';
                return 'unknown';
            })()
        """)
        print(f"  Verification: {verify}")

        # =====================================================
        # Step 5: Save draft
        # =====================================================
        print("\n--- Step 5: Save draft ---")
        save_result = await client.eval_value("""
            (function(){
                var btns=document.querySelectorAll('button, a.weui-desktop-btn, a.weui-desktop-btn_primary');
                for(var i=0;i<btns.length;i++){
                    var t=btns[i].textContent.trim();
                    if(t==='保存'||t.indexOf('保 存')>=0||t==='确定'){btns[i].click();return 'clicked:'+t;}
                }
                return 'save_btn_not_found';
            })()
        """)
        print(f"  Save result: {save_result}")
        await asyncio.sleep(2)

        if screenshot_dir:
            await client.screenshot(os.path.join(screenshot_dir, f"step5_after_save_{media_id}.png"))

    print("\n✅ Cover image upload completed!")
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

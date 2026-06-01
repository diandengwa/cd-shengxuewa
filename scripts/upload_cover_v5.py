"""
微信公众号草稿封面图上传脚本 v5

通过 CDP 协议操作 Chrome，为指定草稿上传封面图。

关键修复:
  - 使用 DOM.getDocument(depth=10) 加载足够深的 DOM 树
  - 使用 CDP DOM.querySelectorAll 命令（非 JS）直接获取 nodeIds
  - 持久 WebSocket 连接
  - 先用 JS 点击封面区域，触发文件选择 UI

使用方式:
    python upload_cover_v5.py --media-id <media_id> --cover <封面图路径>
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
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.msg_id = 0
        self._ws = None

    async def __aenter__(self):
        self._ws = await websockets.connect(self.ws_url, max_size=50*1024*1024)
        return self

    async def __aexit__(self, *_):
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send(self, method, params=None, timeout=30):
        if not self._ws:
            raise RuntimeError("WS not connected")
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
                var links=document.querySelectorAll('a[href*="token="]');
                for(var i=0;i<links.length;i++){
                    var m=links[i].href.match(/token=(\\d+)/);
                    if(m) return m[1];
                }
                return null;
            })()
        """)
        return token

    async def get_file_input_node_id(self):
        """
        Use CDP DOM.getDocument + DOM.querySelectorAll to get file input nodeId.
        Returns nodeId (int) or 0.
        """
        # Load DOM tree with enough depth (10 should cover input elements)
        doc_result = await self.send("DOM.getDocument", {"depth": 10})
        root_id = doc_result.get("result", {}).get("root", {}).get("nodeId", 0)
        if not root_id:
            # Fallback: use depth=-1 (full tree)
            doc_result = await self.send("DOM.getDocument", {"depth": -1})
            root_id = doc_result.get("result", {}).get("root", {}).get("nodeId", 0)
        if not root_id:
            return 0

        # Use CDP DOM.querySelectorAll (returns nodeIds directly)
        query_result = await self.send("DOM.querySelectorAll", {
            "nodeId": root_id,
            "selector": 'input[type="file"]'
        })
        node_ids = query_result.get("result", {}).get("nodeIds", [])
        if node_ids:
            return node_ids[0]
        return 0

    async def set_file_on_node(self, file_path, node_id):
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
        print(f"ERROR: cover not found: {abs_cover}")
        return False

    try:
        tabs = get_tabs()
    except Exception as e:
        print(f"ERROR: CDP connection failed: {e}")
        return False

    wechat_tab = None
    for tab in tabs:
        if "mp.weixin.qq.com" in tab.get("url", ""):
            wechat_tab = tab
            break
    if not wechat_tab:
        print("ERROR: no WeChat MP tab. Please open mp.weixin.qq.com in Chrome.")
        return False

    ws_url = wechat_tab.get("webSocketDebuggerUrl", "")
    if not ws_url:
        print("ERROR: no WebSocket URL")
        return False

    print(f"Connected to tab: {wechat_tab.get('title', '?')[:50]}")

    async with CDPClient(ws_url) as client:
        # =====================================================
        # Step 1: Get token
        # =====================================================
        print("\n--- Step 1: Get token ---")
        token = await client.get_token()
        if not token:
            print("ERROR: cannot get token. Please login to mp.weixin.qq.com first.")
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
            await client.screenshot(os.path.join(screenshot_dir, f"step2_{media_id}.png"))

        page_title = await client.eval_value("document.title")
        page_url = await client.eval_value("window.location.href")
        print(f"  title: {page_title}")
        print(f"  url:   {page_url[:120]}")

        if "login" in (page_url or "").lower() or "扫码" in (page_title or ""):
            print("ERROR: redirected to login page")
            return False

        # =====================================================
        # Step 3: Wait + explore DOM
        # =====================================================
        print("\n--- Step 3: Explore DOM ---")
        await asyncio.sleep(5)

        dom_summary = await client.eval_value("""
            (function(){
                var s={fi:0,iframes:0,buttons:[]};
                s.fi=document.querySelectorAll('input[type="file"]').length;
                s.iframes=document.querySelectorAll('iframe').length;
                var btns=document.querySelectorAll('button,.weui-desktop-btn,.weui-desktop-btn_primary');
                for(var i=0;i<btns.length;i++){
                    var t=btns[i].textContent.trim(); if(t&&t.length<15) s.buttons.push(t);
                }
                return JSON.stringify(s);
            })()
        """)
        print(f"  DOM: {dom_summary}")
        try:
            dom = json.loads(dom_summary) if dom_summary else {}
        except Exception:
            dom = {}
        fi_count = dom.get("fi", 0)
        print(f"  file inputs: {fi_count}")

        # =====================================================
        # Step 4: Click cover area to trigger upload UI
        # =====================================================
        print("\n--- Step 4: Click cover area + upload ---")

        # Try clicking cover area first (may reveal the real file input)
        click_result = await client.evaluate("""
            (function(){
                // Common WeChat MP cover area selectors
                var sels=['.cover-area','.js-cover-area','.media_cover_picker',
                         '.cover_inner','#js_cover','.js_cover','.icon_cover',
                         '.weui-desktop-form__cell_cover'];
                for(var i=0;i<sels.length;i++){
                    var el=document.querySelector(sels[i]);
                    if(el){el.click();return 'clicked:'+sels[i];}
                }
                // Try finding by text
                var all=document.querySelectorAll('*');
                for(var j=0;j<all.length;j++){
                    var t=all[j].textContent.trim();
                    if((t==='封面'||t==='选择封面'||t.indexOf('上传封面')>=0)&&all[j].offsetParent!==null){
                        all[j].click(); return 'clicked_text:'+t;
                    }
                }
                return 'no_cover';
            })()
        """)
        print(f"  cover click: {click_result.get('result',{}).get('result',{}).get('value','?')}")
        await asyncio.sleep(2)

        # Re-check file inputs after clicking
        fi_count_after = await client.eval_value("document.querySelectorAll('input[type=\"file\"]').length")
        print(f"  file inputs after click: {fi_count_after}")
        if fi_count_after > fi_count:
            fi_count = fi_count_after

        if fi_count == 0:
            print("ERROR: no file input found even after clicking cover area")
            if screenshot_dir:
                await client.screenshot(os.path.join(screenshot_dir, f"step4_no_fi_{media_id}.png"))
            return False

        # =====================================================
        # Step 5: Get nodeId + set file
        # =====================================================
        print(f"\n--- Step 5: Set file on input (fi_count={fi_count}) ---")
        node_id = await client.get_file_input_node_id()
        print(f"  nodeId from CDP DOM.querySelectorAll: {node_id}")

        if not node_id:
            print("ERROR: CDP DOM.querySelectorAll returned no nodeId")
            if screenshot_dir:
                await client.screenshot(os.path.join(screenshot_dir, f"step5_no_node_{media_id}.png"))
            return False

        print(f"  Setting file: {os.path.basename(abs_cover)}")
        set_result = await client.set_file_on_node(abs_cover, node_id)
        if "error" in set_result:
            print(f"ERROR: setFileInputFiles failed: {set_result.get('error')}")
            return False

        print("  File set! Waiting for WeChat to process...")
        await asyncio.sleep(5)

        if screenshot_dir:
            await client.screenshot(os.path.join(screenshot_dir, f"step5_after_upload_{media_id}.png"))

        # =====================================================
        # Step 6: Save draft
        # =====================================================
        print("\n--- Step 6: Save draft ---")
        save_result = await client.evaluate("""
            (function(){
                var btns=document.querySelectorAll('button,.weui-desktop-btn,.weui-desktop-btn_primary,a.weui-desktop-btn_primary');
                for(var i=0;i<btns.length;i++){
                    var t=btns[i].textContent.trim();
                    // 匹配"保存"、"保存为草稿"、"保 存"（微信有时加空格）
                    if(t==='保存'||t.indexOf('保存')>=0||t.indexOf('保 存')>=0||t==='确定'){
                        btns[i].click(); return 'clicked:'+t;
                    }
                }
                return 'save_not_found';
            })()
        """)
        print(f"  save: {save_result.get('result',{}).get('result',{}).get('value','?')}")
        await asyncio.sleep(2)

        if screenshot_dir:
            await client.screenshot(os.path.join(screenshot_dir, f"step6_after_save_{media_id}.png"))

        print("\n✅ Cover upload flow done!")
    return True


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-id", required=True)
    parser.add_argument("--cover", required=True)
    parser.add_argument("--screenshot-dir", default="D:/opc/pipeline-logs")
    args = parser.parse_args()
    result = await upload_cover(args.media_id, args.cover, args.screenshot_dir)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    asyncio.run(main())

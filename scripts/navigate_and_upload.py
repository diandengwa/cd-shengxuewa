#!/usr/bin/env python3
"""
Navigate Chrome CDP to WeChat draft editor, then upload cover.
Usage: python navigate_and_upload.py --media-id XXXXX --cover <path> --token <token>
"""
import json
import subprocess
import sys
import time
import websockets
import asyncio

WS_URL = "ws://127.0.0.1:9222/devtools/page/{page_id}"

async def get_page_ws():
    """Find the WeChat mp page WS URL."""
    proc = subprocess.run(
        ["curl", "-s", "http://127.0.0.1:9222/json/list"],
        capture_output=True, text=True
    )
    pages = json.loads(proc.stdout)
    for p in pages:
        url = p.get("url", "")
        if "mp.weixin.qq.com" in url and p.get("type") == "page":
            return p["webSocketDebuggerUrl"], p["id"]
    return None, None

async def navigate_to(ws_url, url):
    """Navigate Chrome to a URL via CDP."""
    async with websockets.connect(ws_url) as ws:
        # Enable Page domain
        await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await ws.recv()

        # Navigate
        await ws.send(json.dumps({
            "id": 2,
            "method": "Page.navigate",
            "params": {"url": url}
        }))
        resp = await ws.recv()
        print(f"Navigate response: {resp}")

        # Wait for page to load
        print("Waiting for page to load...")
        for _ in range(30):
            try:
                await ws.send(json.dumps({"id": 3, "method": "Page.getFrameTree"}))
                await ws.recv()
                break
            except:
                pass
            await asyncio.sleep(1)
        print("Page should be loaded now.")

async def main():
    if len(sys.argv) < 7:
        print("Usage: python navigate_and_upload.py --media-id X --cover <path> --token <token>")
        sys.exit(1)

    media_id = sys.argv[2]
    cover_path = sys.argv[4]
    token = sys.argv[6]

    # Find WeChat page
    ws_url, page_id = await get_page_ws()
    if not ws_url:
        print("ERROR: No WeChat mp page found. Please open Chrome with CDP first.")
        sys.exit(1)

    print(f"Found WeChat page: {ws_url}")

    # Navigate to draft editor
    editor_url = (
        f"https://mp.weixin.qq.com/cgi-bin/appmsg"
        f"?t=media/appmsg_edit_v2&action=edit&isNew=1"
        f"&media_id={media_id}&token={token}&lang=zh_CN"
    )
    print(f"Navigating to: {editor_url}")
    await navigate_to(ws_url, editor_url)
    await asyncio.sleep(5)  # Wait for page to fully load

    # Now run upload_cover_v5.py
    print(f"Running upload_cover_v5.py...")
    result = subprocess.run(
        [sys.executable, "scripts/upload_cover_v5.py",
         "--media-id", media_id, "--cover", cover_path],
        capture_output=True, text=True, cwd="D:/opc"
    )
    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr}")

if __name__ == "__main__":
    asyncio.run(main())

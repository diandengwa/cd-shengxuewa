#!/usr/bin/env python3
"""
Use CDP to navigate Chrome to WeChat draft editor,
then run upload_cover_v5.py to upload the cover.

Usage:
    python cdp_upload_cover.py --media-id XXXX --cover <path> --token <token>
"""

import json
import subprocess
import sys
import time
import websockets
import asyncio

# WeChat token (from Chrome tab URL)
TOKEN = "1766745777"

# CDP page WS URL (find the mp.weixin.qq.com tab)
CDP_PORT = 9222


async def find_wechat_tab():
    """Find the WeChat mp page's WebSocket URL."""
    proc = subprocess.run(
        ["curl", "-s", f"http://127.0.0.1:{CDP_PORT}/json/list"],
        capture_output=True, text=True
    )
    pages = json.loads(proc.stdout)
    for p in pages:
        url = p.get("url", "")
        if "mp.weixin.qq.com" in url and p.get("type") == "page":
            return p["webSocketDebuggerUrl"], p["id"], url
    return None, None, None


async def navigate_and_upload(media_id: str, cover_path: str, token: str):
    """Navigate Chrome to draft editor, then upload cover."""
    ws_url, _, current_url = await find_wechat_tab()
    if not ws_url:
        print("ERROR: No WeChat mp tab found. Please open Chrome with CDP.")
        return False

    print(f"Connected to WeChat tab: {ws_url[:60]}...")
    print(f"Current URL: {current_url[:80]}...")

    async with websockets.connect(ws_url) as ws:
        # Enable Page domain
        await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await ws.recv()

        # Navigate to draft editor
        editor_url = (
            f"https://mp.weixin.qq.com/cgi-bin/appmsg"
            f"?t=media/appmsg_edit_v2&action=edit&isNew=1"
            f"&media_id={media_id}&token={token}&lang=zh_CN"
        )
        print(f"Navigating to draft editor...")
        await ws.send(json.dumps({
            "id": 2,
            "method": "Page.navigate",
            "params": {"url": editor_url}
        }))
        nav_resp = await ws.recv()
        print(f"Navigate response: {nav_resp[:200]}")

        # Wait for page to load (listen for loadEventFired)
        print("Waiting for page to load (up to 15s)...")
        for _ in range(30):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                if "Page.loadEventFired" in msg or "Page.frameStoppedLoading" in msg:
                    print("Page loaded!")
                    break
            except asyncio.TimeoutError:
                pass
            # Send a ping to keep connection alive
            await ws.send(json.dumps({"id": 99, "method": "Page.getNavigationHistory"}))
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

        await asyncio.sleep(3)  # Extra wait for JS to settle

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

    return result.returncode == 0


def main():
    if len(sys.argv) < 7:
        print("Usage: python cdp_upload_cover.py --media-id X --cover <path> --token <token>")
        sys.exit(1)

    media_id = sys.argv[2]
    cover_path = sys.argv[4]
    token = sys.argv[6]

    success = asyncio.run(navigate_and_upload(media_id, cover_path, token))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

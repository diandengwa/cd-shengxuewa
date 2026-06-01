"""快速检查 Chrome CDP 连接和微信公众号后台状态"""
import json
import urllib.request
import time

CDP_PORT = 9222

# 获取标签页
url = f"http://127.0.0.1:{CDP_PORT}/json/list"
with urllib.request.urlopen(url, timeout=5) as resp:
    tabs = json.loads(resp.read().decode())

print("=== Chrome 标签页 ===")
for i, tab in enumerate(tabs):
    print(f"  [{i}] {tab.get('title', 'unknown')[:60]}")
    print(f"      URL: {tab.get('url', '')[:100]}")
    print()

# 找到微信公众号相关的标签页
wechat_tabs = [t for t in tabs if "mp.weixin.qq.com" in t.get("url", "")]
if wechat_tabs:
    print(f"找到 {len(wechat_tabs)} 个微信公众号标签页")
else:
    print("未找到微信公众号标签页")
    # 检查是否有空白页可以用
    blank_tabs = [t for t in tabs if "chrome://" in t.get("url", "") or "about:blank" in t.get("url", "")]
    if blank_tabs:
        print(f"可以使用空白标签页: {blank_tabs[0].get('id', '')}")

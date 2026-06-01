"""
微信公众号草稿封面图上传脚本

通过 Chrome CDP 协议操作微信公众号后台，为指定草稿上传封面图。

使用方式:
    python upload_cover.py --media-id <草稿media_id> --cover <封面图路径>

前置条件:
    - Chrome 已启动并开启 CDP 端口 (9222)
    - 使用已登录微信公众号的 Chrome profile
    - 微信公众号后台已登录
"""

import argparse
import json
import os
import sys
import time
import base64
import urllib.request
import urllib.error


CDP_PORT = 9222
CDP_HOST = "127.0.0.1"


def cdp_get_tabs():
    """获取所有 Chrome 标签页"""
    url = f"http://{CDP_HOST}:{CDP_PORT}/json/list"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def cdp_new_tab(url="about:blank"):
    """新建标签页"""
    new_url = f"http://{CDP_HOST}:{CDP_PORT}/json/new?{urllib.parse.quote(url)}"
    req = urllib.request.Request(new_url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def cdp_send(ws_url, method, params=None, timeout=30):
    """通过 WebSocket 发送 CDP 命令"""
    import asyncio
    import websockets

    async def _send():
        async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
            msg_id = 1
            msg = {"id": msg_id, "method": method, "params": params or {}}
            await ws.send(json.dumps(msg))
            while True:
                response = await asyncio.wait_for(ws.recv(), timeout=timeout)
                data = json.loads(response)
                if data.get("id") == msg_id:
                    return data

    return asyncio.run(_send())


def cdp_evaluate(ws_url, expression, timeout=15):
    """在页面中执行 JavaScript"""
    return cdp_send(ws_url, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True
    }, timeout=timeout)


def wait_for_page(ws_url, timeout=15):
    """等待页面加载完成"""
    for _ in range(timeout * 2):
        result = cdp_evaluate(ws_url, "document.readyState")
        if result.get("result", {}).get("result", {}).get("value") == "complete":
            return True
        time.sleep(0.5)
    return False


def get_page_title(ws_url):
    """获取页面标题"""
    result = cdp_evaluate(ws_url, "document.title")
    return result.get("result", {}).get("result", {}).get("value", "")


def find_or_create_draft_tab(media_id):
    """找到或创建草稿编辑页面的标签页"""
    tabs = cdp_get_tabs()

    # 先找是否已经有该草稿的编辑页面
    target_url = f"appmsg_edit&action=edit&type=77"
    for tab in tabs:
        url = tab.get("url", "")
        if "mp.weixin.qq.com" in url and "appmsg_edit" in url:
            return tab

    # 新建标签页，导航到草稿编辑页
    # 微信公众号草稿编辑 URL 格式：
    # https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&appmsgid={media_id}&token=xxx
    # 但我们不知道 token，所以先进入草稿列表页，再点击编辑
    new_tab = cdp_new_tab("https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77")
    return new_tab


def navigate_to_draft_edit(ws_url, media_id):
    """导航到草稿编辑页面（通过先访问草稿列表再点击编辑的方式）"""
    # 先尝试直接在草稿列表中找到并点击编辑
    # 步骤1: 导航到内容管理-草稿箱
    draft_list_url = "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&type=10&action=list"
    cdp_send(ws_url, "Page.navigate", {"url": draft_list_url})
    time.sleep(3)
    wait_for_page(ws_url, 10)
    time.sleep(2)  # 额外等待动态内容加载

    title = get_page_title(ws_url)
    print(f"当前页面标题: {title}")

    # 检查是否需要登录
    result = cdp_evaluate(ws_url, "document.querySelector('.weui-desktop-btn_primary')?.textContent || ''")
    login_btn = result.get("result", {}).get("result", {}).get("value", "")
    if "登录" in login_btn or "扫码" in login_btn:
        print("❌ 需要登录微信公众号！请在 Chrome 中手动扫码登录。")
        return False

    return True


def click_edit_draft(ws_url, media_id):
    """在草稿列表中点击指定草稿的编辑按钮"""
    # 尝试找到草稿列表项并点击编辑
    js_code = f"""
    (function() {{
        // 查找所有草稿条目
        const items = document.querySelectorAll('.appmsg_content_item, .weui-desktop-card, [data-id]');
        for (const item of items) {{
            const editBtn = item.querySelector('.weui-desktop-btn_mini, .weui-desktop-btn_primary, a[href*="appmsg_edit"]');
            if (editBtn) {{
                const href = editBtn.getAttribute('href') || editBtn.closest('a')?.getAttribute('href') || '';
                if (href.includes('{media_id}') || editBtn.textContent.includes('编辑')) {{
                    editBtn.click();
                    return 'clicked: ' + editBtn.textContent.trim();
                }}
            }}
        }}
        return 'not_found';
    }})()
    """
    result = cdp_evaluate(ws_url, js_code)
    value = result.get("result", {}).get("result", {}).get("value", "")
    print(f"点击编辑按钮结果: {value}")
    return "clicked" in value


def upload_cover_via_cdp(ws_url, cover_path):
    """通过 CDP 上传封面图到草稿编辑页面的封面区域"""

    # 第一步：找到封面图上传区域并点击
    # 微信公众号编辑页面的封面图上传区域选择器
    js_find_cover = """
    (function() {
        // 封面图区域的各种可能选择器
        const selectors = [
            '.media_cover_picker',
            '.js-cover-area',
            '.cover-area',
            '[data-type="cover"]',
            '.appmsg_edit_tips',
            '.weui-desktop-form__cell_cover',
            '.cover_inner',
            '.js_cover',
            '#js_cover',
            '.icon_cover',
            // 更通用的方式：查找包含"封面"文本的元素
        ];

        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) return 'found_selector: ' + sel;
        }

        // 尝试通过文本内容查找
        const allElements = document.querySelectorAll('div, span, a, label');
        for (const el of allElements) {
            if (el.textContent.trim() === '封面' || el.textContent.trim() === '选择封面') {
                return 'found_text: ' + el.tagName + '.' + el.className;
            }
        }

        // 输出页面结构帮助调试
        const body = document.body.innerHTML;
        const coverRelated = body.match(/封[面图].*?<[\/a-z]*/g);
        if (coverRelated) return 'cover_matches: ' + JSON.stringify(coverRelated.slice(0, 5));

        return 'cover_area_not_found';
    })()
    """

    result = cdp_evaluate(ws_url, js_find_cover)
    value = result.get("result", {}).get("result", {}).get("value", "")
    print(f"查找封面区域结果: {value}")

    # 第二步：设置文件上传拦截器
    abs_cover_path = os.path.abspath(cover_path).replace("/", "\\")
    print(f"准备上传封面图: {abs_cover_path}")

    # 使用 DOM.setFileInputFiles 方式上传
    # 先点击封面区域触发文件选择框，然后拦截文件选择
    js_click_cover = """
    (function() {
        // 尝试点击封面区域
        const coverSelectors = [
            '.media_cover_picker',
            '.js-cover-area',
            '.cover-area',
            '.cover_inner',
            '.js_cover',
            '#js_cover',
        ];

        for (const sel of coverSelectors) {
            const el = document.querySelector(sel);
            if (el) {
                el.click();
                return 'clicked: ' + sel;
            }
        }

        // 尝试找包含封面的可点击元素
        const allElements = document.querySelectorAll('div, span, a, label, button');
        for (const el of allElements) {
            const text = el.textContent.trim();
            if ((text === '封面' || text === '选择封面' || text.includes('上传封面')) && el.offsetParent !== null) {
                el.click();
                return 'clicked_text: ' + text;
            }
        }

        return 'no_cover_element_clicked';
    })()
    """

    result = cdp_evaluate(ws_url, js_click_cover)
    value = result.get("result", {}).get("result", {}).get("value", "")
    print(f"点击封面区域结果: {value}")

    # 第三步：查找文件输入框并设置文件
    time.sleep(1)

    js_find_file_input = """
    (function() {
        const inputs = document.querySelectorAll('input[type="file"]');
        const results = [];
        for (const input of inputs) {
            results.push({
                id: input.id,
                name: input.name,
                className: input.className,
                accept: input.accept,
                parent: input.parentElement?.className || ''
            });
        }
        return JSON.stringify(results);
    })()
    """

    result = cdp_evaluate(ws_url, js_find_file_input)
    value = result.get("result", {}).get("result", {}).get("value", "[]")
    print(f"文件输入框: {value}")

    try:
        file_inputs = json.loads(value)
    except:
        file_inputs = []

    if not file_inputs:
        print("❌ 未找到文件输入框")
        return False

    # 第四步：使用 CDP DOM.setFileInputFiles 上传文件
    # 先获取 input[type=file] 的 backend node id
    js_get_file_input_backend = """
    (function() {
        const input = document.querySelector('input[type="file"]');
        if (!input) return 'no_file_input';
        // 返回一些信息用于定位
        return JSON.stringify({
            id: input.id,
            name: input.name,
            className: input.className
        });
    })()
    """

    result = cdp_evaluate(ws_url, js_get_file_input_backend)
    value = result.get("result", {}).get("result", {}).get("value", "")
    print(f"文件输入框信息: {value}")

    # 使用 DOM.getDocument + DOM.querySelector 获取 backendNodeId
    doc_result = cdp_send(ws_url, "DOM.getDocument", {"depth": 0})
    root_node_id = doc_result.get("result", {}).get("root", {}).get("nodeId", 0)

    # 查找 input[type="file"]
    query_result = cdp_send(ws_url, "DOM.querySelector", {
        "nodeId": root_node_id,
        "selector": 'input[type="file"]'
    })
    backend_node_id = query_result.get("result", {}).get("nodeId", 0)

    if not backend_node_id:
        print("❌ 无法获取文件输入框的 backend node id")
        return False

    print(f"文件输入框 backendNodeId: {backend_node_id}")

    # 设置文件
    set_file_result = cdp_send(ws_url, "DOM.setFileInputFiles", {
        "files": [abs_cover_path],
        "nodeId": backend_node_id
    })

    if "error" in set_file_result:
        print(f"❌ 上传文件失败: {set_file_result.get('error')}")
        return False

    print("✅ 文件已设置到输入框")
    time.sleep(3)  # 等待上传完成

    return True


def save_draft(ws_url):
    """保存草稿"""
    js_save = """
    (function() {
        // 查找保存按钮
        const selectors = [
            '.weui-desktop-btn_primary',
            '#js_submit',
            '.js-save',
            'button[data-type="save"]',
        ];

        for (const sel of selectors) {
            const btns = document.querySelectorAll(sel);
            for (const btn of btns) {
                if (btn.textContent.includes('保存') || btn.textContent.includes('确定')) {
                    btn.click();
                    return 'clicked_save: ' + btn.textContent.trim();
                }
            }
        }
        return 'save_button_not_found';
    })()
    """

    result = cdp_evaluate(ws_url, js_save)
    value = result.get("result", {}).get("result", {}).get("value", "")
    print(f"保存草稿结果: {value}")
    return "clicked_save" in value


def take_screenshot(ws_url, output_path):
    """截图"""
    result = cdp_send(ws_url, "Page.captureScreenshot", {"format": "png"})
    screenshot_data = result.get("result", {}).get("data", "")
    if screenshot_data:
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(screenshot_data))
        print(f"截图已保存: {output_path}")
    return bool(screenshot_data)


def main():
    parser = argparse.ArgumentParser(description="微信公众号草稿封面图上传")
    parser.add_argument("--media-id", required=True, help="草稿 media_id")
    parser.add_argument("--cover", required=True, help="封面图本地路径")
    parser.add_argument("--screenshot", default="", help="截图输出路径（可选）")
    args = parser.parse_args()

    if not os.path.exists(args.cover):
        print(f"❌ 封面图文件不存在: {args.cover}")
        sys.exit(1)

    # 获取 Chrome 标签页
    try:
        tabs = cdp_get_tabs()
    except Exception as e:
        print(f"❌ 无法连接 Chrome CDP: {e}")
        print("请确保 Chrome 已启动并开启了 CDP 端口 (9222)")
        sys.exit(1)

    # 找到微信公众号的标签页
    wechat_tab = None
    for tab in tabs:
        if "mp.weixin.qq.com" in tab.get("url", ""):
            wechat_tab = tab
            break

    if not wechat_tab:
        # 没有微信公众号标签页，使用第一个标签页
        if tabs:
            wechat_tab = tabs[0]
        else:
            print("❌ 没有可用的 Chrome 标签页")
            sys.exit(1)

    ws_url = wechat_tab.get("webSocketDebuggerUrl", "")
    if not ws_url:
        print("❌ 无法获取 WebSocket 调试 URL")
        sys.exit(1)

    print(f"使用标签页: {wechat_tab.get('title', 'unknown')}")

    # 导航到草稿编辑页面
    print("\n--- Step 1: 导航到草稿编辑页面 ---")

    # 直接构造编辑URL（微信公众号的草稿编辑页面）
    # 通过先导航到草稿列表，然后模拟点击编辑
    if not navigate_to_draft_edit(ws_url, args.media_id):
        sys.exit(1)

    # 截图查看当前状态
    if args.screenshot:
        take_screenshot(ws_url, args.screenshot + "_step1.png")

    # 点击编辑草稿
    print("\n--- Step 2: 打开草稿编辑 ---")
    if click_edit_draft(ws_url, args.media_id):
        time.sleep(3)
        wait_for_page(ws_url, 10)
    else:
        # 如果找不到编辑按钮，尝试直接导航到编辑页面
        print("尝试直接导航到草稿编辑页面...")
        # 从草稿列表中获取 token
        js_get_token = """
        (function() {
            const links = document.querySelectorAll('a[href*="appmsg_edit"]');
            if (links.length > 0) {
                return links[0].getAttribute('href');
            }
            // 尝试从 URL 或 cookie 获取 token
            const match = window.location.href.match(/token=(\\d+)/);
            if (match) return 'token=' + match[1];
            return 'no_token_found';
        })()
        """
        result = cdp_evaluate(ws_url, js_get_token)
        token_value = result.get("result", {}).get("result", {}).get("value", "")
        print(f"获取 token: {token_value}")

        if token_value.startswith("token="):
            token = token_value.split("=")[1]
            edit_url = f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&appmsgid={args.media_id}&token={token}"
            cdp_send(ws_url, "Page.navigate", {"url": edit_url})
            time.sleep(3)
            wait_for_page(ws_url, 10)

    if args.screenshot:
        take_screenshot(ws_url, args.screenshot + "_step2.png")

    # 上传封面图
    print("\n--- Step 3: 上传封面图 ---")
    success = upload_cover_via_cdp(ws_url, args.cover)

    if args.screenshot:
        take_screenshot(ws_url, args.screenshot + "_step3.png")

    if success:
        print("\n--- Step 4: 保存草稿 ---")
        save_draft(ws_url)
        time.sleep(2)

        if args.screenshot:
            take_screenshot(ws_url, args.screenshot + "_step4.png")

    print("\n✅ 封面图上传流程完成")


if __name__ == "__main__":
    main()

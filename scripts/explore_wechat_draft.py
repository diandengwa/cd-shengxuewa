"""
探索微信公众号草稿编辑页面的 DOM 结构
用于了解封面图上传区域的选择器
"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp('http://127.0.0.1:9222')
        ctx = browser.contexts[0]
        page = ctx.pages[0]

        # Step 1: 进入草稿箱
        print("=== Step 1: 导航到草稿箱 ===")
        await page.goto("https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&type=10&action=list&lang=zh_CN&token=1766745777")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        title = await page.title()
        url = page.url
        print(f"页面标题: {title}")
        print(f"URL: {url}")

        # 截图
        await page.screenshot(path="D:/opc/pipeline-logs/draft_list_explore.png")
        print("截图已保存: draft_list_explore.png")

        # 获取草稿列表的结构
        list_html = await page.evaluate("""
        () => {
            // 找到草稿列表区域
            const listContainer = document.querySelector('.appmsg_list, .weui-desktop-card-group, .card_appmsg_list, [class*="appmsg_list"], [class*="draft"]');
            if (listContainer) {
                return {
                    tag: listContainer.tagName,
                    className: listContainer.className,
                    childCount: listContainer.children.length,
                    firstChildTag: listContainer.children[0]?.tagName,
                    firstChildClass: listContainer.children[0]?.className,
                    innerHTML: listContainer.innerHTML.substring(0, 2000)
                };
            }

            // 如果找不到列表容器，输出 body 的部分 HTML
            const body = document.body.innerHTML;
            // 搜索草稿相关的关键词
            const matches = [];
            const keywords = ['草稿', '编辑', 'appmsg', 'draft', 'media_id', '504031705', '504031706'];
            for (const kw of keywords) {
                const idx = body.indexOf(kw);
                if (idx >= 0) {
                    matches.push({
                        keyword: kw,
                        context: body.substring(Math.max(0, idx - 50), idx + 100)
                    });
                }
            }

            return {
                listNotFound: true,
                keywordMatches: matches.slice(0, 10),
                bodySnippet: body.substring(0, 1000)
            };
        }
        """)
        print(f"\n草稿列表结构: {list_html}")

        # Step 2: 尝试点击第一个草稿的编辑按钮
        print("\n=== Step 2: 查找草稿编辑链接 ===")
        edit_links = await page.evaluate("""
        () => {
            const links = document.querySelectorAll('a[href*="appmsg_edit"]');
            return Array.from(links).map(a => ({
                href: a.getAttribute('href'),
                text: a.textContent.trim().substring(0, 50),
                className: a.className
            }));
        }
        """)
        print(f"编辑链接: {edit_links}")

        # 也查找所有可能的编辑按钮
        edit_buttons = await page.evaluate("""
        () => {
            const buttons = document.querySelectorAll('button, a, span');
            const editBtns = [];
            for (const btn of buttons) {
                const text = btn.textContent.trim();
                if (text === '编辑' || text.includes('编辑')) {
                    editBtns.push({
                        tag: btn.tagName,
                        text: text.substring(0, 30),
                        className: btn.className,
                        href: btn.getAttribute('href') || '',
                        parent: btn.parentElement?.className || ''
                    });
                }
            }
            return editBtns;
        }
        """)
        print(f"编辑按钮: {edit_buttons}")

        # Step 3: 如果找到了编辑链接，打开一个看看编辑页面的封面区域
        if edit_links:
            first_link = edit_links[0].get('href', '')
            if first_link:
                full_url = first_link if first_link.startswith('http') else f"https://mp.weixin.qq.com{first_link}"
                print(f"\n=== Step 3: 打开编辑页面 ===")
                print(f"URL: {full_url}")
                await page.goto(full_url)
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(3)

                title = await page.title()
                print(f"编辑页面标题: {title}")

                # 截图
                await page.screenshot(path="D:/opc/pipeline-logs/draft_edit_explore.png")
                print("截图已保存: draft_edit_explore.png")

                # 查找封面相关区域
                cover_info = await page.evaluate("""
                () => {
                    // 查找所有包含"封面"文本的元素
                    const coverElements = [];
                    const allElements = document.querySelectorAll('*');
                    for (const el of allElements) {
                        const text = el.textContent.trim();
                        if ((text.includes('封面') || text.includes('cover')) && el.children.length < 3) {
                            coverElements.push({
                                tag: el.tagName,
                                text: text.substring(0, 50),
                                className: el.className,
                                id: el.id,
                                parent: el.parentElement?.className || ''
                            });
                        }
                    }

                    // 查找 input[type="file"]
                    const fileInputs = Array.from(document.querySelectorAll('input[type="file"]')).map(input => ({
                        id: input.id,
                        name: input.name,
                        className: input.className,
                        accept: input.accept
                    }));

                    // 查找图片上传相关元素
                    const uploadElements = Array.from(document.querySelectorAll('[class*="upload"], [class*="cover"], [class*="thumb"], [id*="cover"], [id*="thumb"]')).map(el => ({
                        tag: el.tagName,
                        className: el.className,
                        id: el.id,
                        text: el.textContent.trim().substring(0, 50)
                    }));

                    return {
                        coverElements: coverElements.slice(0, 10),
                        fileInputs,
                        uploadElements: uploadElements.slice(0, 15)
                    };
                }
                """)
                print(f"\n封面区域信息: {cover_info}")

asyncio.run(main())

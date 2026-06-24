#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号自动排版与草稿自动上传脚本
根据创始人规范进行富文本排版（17px, 1.8 行高, 绿色引用块无表情等）
并将排版后的 HTML 和封面图自动上传至微信公众号草稿箱。
"""

import os
import re
import sys
import argparse
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

# 确保能 import 项目中的 app 模块
scripts_dir = Path(__file__).parent.resolve()
root_dir = scripts_dir.parent.resolve()
sys.path.insert(0, str(root_dir))

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("md2wechat")

try:
    import httpx
except ImportError:
    logger.error("缺少依赖库 httpx，请在环境中安装。")
    sys.exit(1)

# 加载 .env 环境变量
from dotenv import load_dotenv
load_dotenv(root_dir / ".env")

from app.wechat import get_access_token


def remove_emoji(text: str) -> str:
    """过滤文本中的常见 emoji 和杂项符号，保持引用块的严肃性"""
    emoji_pattern = re.compile(
        '['
        '\U00010000-\U0010ffff'  # 4字节的emoji
        '\u2600-\u27BF'          # 杂项符号及印刷符号
        '\u2300-\u23FF'          # 杂项技术符号
        ']+', flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)


def markdown_to_html(md_text: str) -> str:
    """
    将内容工厂输出的 Markdown 转换为符合微信公众号排版品味规范的 HTML。
    - 字体: 17px
    - 行高: 1.8
    - 颜色: #2b2b2b
    - 引用块: 背景 #f5f5f5, 左边框 #07C160 (3px), 剥离 emoji
    - 二级标题: 字体 18px, 加粗, 带有微弱下划线
    - 列表和有序步骤: 结构清晰, 数字加粗着色
    """
    lines = md_text.splitlines()
    html_parts = []
    
    in_list = False
    in_quote = False
    quote_lines = []
    in_code_block = False
    code_lines = []
    in_ordered_list = False
    ordered_list_items = []
    
    for line in lines:
        stripped = line.strip()
        
        # 处理代码块
        if stripped.startswith('```'):
            if in_code_block:
                # 结束代码块
                in_code_block = False
                code_content = '\n'.join(code_lines)
                # 转义 HTML 特殊字符
                code_content = (code_content
                    .replace('&', '&amp;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;')
                    .replace('"', '&quot;')
                    .replace("'", '&#39;'))
                html_parts.append(
                    f'<pre style="background-color: #f8f8f8; border: 1px solid #e0e0e0; '
                    f'border-radius: 4px; padding: 16px; margin: 1.2em 0; '
                    f'font-size: 14px; line-height: 1.6; overflow-x: auto; '
                    f'color: #333; font-family: Consolas, Monaco, monospace;">'
                    f'<code>{code_content}</code></pre>'
                )
                code_lines = []
            else:
                in_code_block = True
            continue
        
        if in_code_block:
            code_lines.append(line)
            continue
        
        # 1. 处理引用块 <blockquote>
        if stripped.startswith('>'):
            if not in_quote:
                in_quote = True
                quote_lines = []
            content = stripped[1:].strip()
            quote_lines.append(content)
            continue
        else:
            if in_quote:
                in_quote = False
                quote_content = "<br/>".join(quote_lines)
                quote_content = remove_emoji(quote_content)
                html_parts.append(
                    f'<blockquote style="background-color: #f5f5f5; border-left: 3px solid #07C160; '
                    f'padding: 12px 16px; margin: 1.5em 0; color: #555; font-size: 16px; line-height: 1.7; '
                    f'border-radius: 2px; word-wrap: break-word;">'
                    f'{quote_content}</blockquote>'
                )
                quote_lines = []
        
        # 2. 处理空行
        if not stripped:
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            if in_ordered_list:
                html_parts.append('</ol>')
                in_ordered_list = False
                ordered_list_items = []
            continue
        
        # 3. 处理标题
        if stripped.startswith('## '):
            title_text = stripped[3:].strip()
            html_parts.append(
                f'<h2 style="font-size: 18px; font-weight: bold; color: #2b2b2b; '
                f'margin: 1.5em 0 0.8em 0; padding-bottom: 8px; '
                f'border-bottom: 1px solid #e8e8e8;">{title_text}</h2>'
            )
            continue
        
        if stripped.startswith('### '):
            title_text = stripped[4:].strip()
            html_parts.append(
                f'<h3 style="font-size: 17px; font-weight: bold; color: #2b2b2b; '
                f'margin: 1.2em 0 0.6em 0;">{title_text}</h3>'
            )
            continue
        
        # 4. 处理无序列表
        if stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                in_list = True
                html_parts.append('<ul style="padding-left: 2em; margin: 0.8em 0;">')
            item_content = stripped[2:].strip()
            html_parts.append(
                f'<li style="font-size: 17px; line-height: 1.8; color: #2b2b2b; '
                f'margin-bottom: 0.3em;">{item_content}</li>'
            )
            continue
        
        # 5. 处理有序列表
        ordered_match = re.match(r'^(\d+)\.\s+(.*)', stripped)
        if ordered_match:
            if not in_ordered_list:
                in_ordered_list = True
                ordered_list_items = []
                html_parts.append('<ol style="padding-left: 2em; margin: 0.8em 0;">')
            item_num = ordered_match.group(1)
            item_content = ordered_match.group(2)
            html_parts.append(
                f'<li style="font-size: 17px; line-height: 1.8; color: #2b2b2b; '
                f'margin-bottom: 0.3em;">'
                f'<span style="font-weight: bold; color: #07C160;">{item_num}.</span> '
                f'{item_content}</li>'
            )
            continue
        
        # 6. 处理普通段落（包含内联样式）
        # 处理加粗 **text**
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        # 处理斜体 *text*
        line = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
        # 处理行内代码 `code`
        line = re.sub(r'`([^`]+)`', r'<code style="background-color: #f0f0f0; padding: 2px 6px; '
                     r'border-radius: 3px; font-size: 15px; color: #d63384;">\1</code>', line)
        
        html_parts.append(
            f'<p style="font-size: 17px; line-height: 1.8; color: #2b2b2b; '
            f'margin: 0.5em 0; word-wrap: break-word;">{line}</p>'
        )
    
    # 关闭未闭合的标签
    if in_quote:
        quote_content = "<br/>".join(quote_lines)
        quote_content = remove_emoji(quote_content)
        html_parts.append(
            f'<blockquote style="background-color: #f5f5f5; border-left: 3px solid #07C160; '
            f'padding: 12px 16px; margin: 1.5em 0; color: #555; font-size: 16px; line-height: 1.7; '
            f'border-radius: 2px; word-wrap: break-word;">'
            f'{quote_content}</blockquote>'
        )
    
    if in_list:
        html_parts.append('</ul>')
    
    if in_ordered_list:
        html_parts.append('</ol>')
    
    if in_code_block:
        # 未闭合的代码块，直接输出
        code_content = '\n'.join(code_lines)
        code_content = (code_content
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))
        html_parts.append(
            f'<pre style="background-color: #f8f8f8; border: 1px solid #e0e0e0; '
            f'border-radius: 4px; padding: 16px; margin: 1.2em 0; '
            f'font-size: 14px; line-height: 1.6; overflow-x: auto; '
            f'color: #333; font-family: Consolas, Monaco, monospace;">'
            f'<code>{code_content}</code></pre>'
        )
    
    return '\n'.join(html_parts)


def wrap_full_html(body_html: str, title: str = "") -> str:
    """
    将 body_html 包装成完整的微信公众号文章 HTML。
    包含基础样式重置和文章容器。
    """
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #ffffff;">
    <div style="max-width: 677px; margin: 0 auto; padding: 20px 16px;">
        {body_html}
    </div>
</body>
</html>'''


def read_md_file(file_path: Path) -> Optional[str]:
    """读取 Markdown 文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"读取文件 {file_path} 失败: {e}")
        return None


def extract_title_from_md(md_text: str) -> str:
    """从 Markdown 文本中提取标题（第一个 # 开头的行）"""
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith('# ') and not stripped.startswith('## '):
            return stripped[2:].strip()
    return ""


def upload_draft(
    access_token: str,
    title: str,
    html_content: str,
    cover_media_id: Optional[str] = None,
    author: str = "成都K12升学参谋",
    digest: str = ""
) -> Optional[Dict[str, Any]]:
    """
    上传草稿到微信公众号
    https://developers.weixin.qq.com/doc/offiaccount/Draft_Box/Add_draft.html
    """
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
    
    # 构建文章内容
    articles = [{
        "title": title,
        "author": author,
        "digest": digest,
        "content": html_content,
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }]
    
    if cover_media_id:
        articles[0]["thumb_media_id"] = cover_media_id
    
    payload = {
        "articles": articles
    }
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            result = response.json()
            
            if result.get("errcode") == 0:
                media_id = result.get("media_id")
                logger.info(f"草稿上传成功！media_id: {media_id}")
                return result
            else:
                logger.error(f"草稿上传失败: {result.get('errmsg', '未知错误')}")
                return None
    except Exception as e:
        logger.error(f"草稿上传请求异常: {e}")
        return None


def upload_image(
    access_token: str,
    image_path: Path
) -> Optional[str]:
    """
    上传图片到微信公众号素材库，返回 media_id
    https://developers.weixin.qq.com/doc/offiaccount/Asset_Management/New_temporary_materials.html
    """
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"
    
    try:
        with open(image_path, 'rb') as f:
            files = {'media': (image_path.name, f, 'image/jpeg')}
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, files=files)
                result = response.json()
                
                if result.get("errcode") == 0 or "media_id" in result:
                    media_id = result.get("media_id")
                    logger.info(f"图片上传成功！media_id: {media_id}")
                    return media_id
                else:
                    logger.error(f"图片上传失败: {result.get('errmsg', '未知错误')}")
                    return None
    except Exception as e:
        logger.error(f"图片上传请求异常: {e}")
        return None


def process_md_file(
    md_path: Path,
    access_token: Optional[str] = None,
    cover_path: Optional[Path] = None,
    auto_upload: bool = False
) -> bool:
    """
    处理单个 Markdown 文件：转换为 HTML 并可选上传到微信公众号
    """
    logger.info(f"开始处理文件: {md_path}")
    
    # 读取 Markdown 文件
    md_text = read_md_file(md_path)
    if not md_text:
        return False
    
    # 提取标题
    title = extract_title_from_md(md_text)
    if not title:
        title = md_path.stem
        logger.warning(f"未找到标题，使用文件名作为标题: {title}")
    
    # 转换为 HTML
    body_html = markdown_to_html(md_text)
    full_html = wrap_full_html(body_html, title)
    
    # 保存 HTML 文件
    html_path = md_path.with_suffix('.html')
    try:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(full_html)
        logger.info(f"HTML 文件已保存: {html_path}")
    except Exception as e:
        logger.error(f"保存 HTML 文件失败: {e}")
        return False
    
    # 如果需要自动上传到微信公众号
    if auto_upload and access_token:
        # 上传封面图（如果有）
        cover_media_id = None
        if cover_path and cover_path.exists():
            cover_media_id = upload_image(access_token, cover_path)
            if not cover_media_id:
                logger.warning("封面图上传失败，将继续上传草稿（无封面）")
        
        # 生成摘要（取前100个字符）
        digest = ""
        for line in md_text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and not stripped.startswith('>') and not stripped.startswith('```'):
                digest = stripped[:100]
                break
        
        # 上传草稿
        result = upload_draft(
            access_token=access_token,
            title=title,
            html_content=full_html,
            cover_media_id=cover_media_id,
            digest=digest
        )
        
        if result:
            logger.info(f"草稿上传成功！标题: {title}")
            return True
        else:
            logger.error(f"草稿上传失败！标题: {title}")
            return False
    
    return True


def main():
    """主函数：解析参数并执行转换"""
    parser = argparse.ArgumentParser(
        description="Markdown 转微信公众号富文本 HTML 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 转换单个文件
  python scripts/md2wechat.py content/article.md
  
  # 转换整个目录
  python scripts/md2wechat.py content/
  
  # 转换并上传到微信公众号
  python scripts/md2wechat.py content/article.md --upload --cover cover.jpg
  
  # 指定输出目录
  python scripts/md2wechat.py content/article.md --output-dir output/
        """
    )
    
    parser.add_argument(
        'input',
        type=str,
        help='输入的 Markdown 文件或目录路径'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        default=None,
        help='输出 HTML 文件的目录（默认与输入文件同目录）'
    )
    
    parser.add_argument(
        '--upload',
        action='store_true',
        help='自动上传到微信公众号草稿箱'
    )
    
    parser.add_argument(
        '--cover',
        type=str,
        default=None,
        help='封面图片路径（用于草稿箱上传）'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='输出详细日志'
    )
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # 解析输入路径
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"输入路径不存在: {input_path}")
        sys.exit(1)
    
    # 获取 access_token（如果需要上传）
    access_token = None
    if args.upload:
        try:
            access_token = get_access_token()
            if not access_token:
                logger.error("获取 access_token 失败，无法上传草稿")
                sys.exit(1)
        except Exception as e:
            logger.error(f"获取 access_token 异常: {e}")
            sys.exit(1)
    
    # 解析封面图路径
    cover_path = None
    if args.cover:
        cover_path = Path(args.cover)
        if not cover_path.exists():
            logger.warning(f"封面图不存在: {cover_path}")
            cover_path = None
    
    # 处理文件或目录
    if input_path.is_file():
        # 处理单个文件
        success = process_md_file(
            md_path=input_path,
            access_token=access_token,
            cover_path=cover_path,
            auto_upload=args.upload
        )
        if not success:
            logger.error(f"处理文件失败: {input_path}")
            sys.exit(1)
    else:
        # 处理目录下的所有 .md 文件
        md_files = list(input_path.glob("*.md"))
        if not md_files:
            logger.error(f"目录中未找到 .md 文件: {input_path}")
            sys.exit(1)
        
        logger.info(f"找到 {len(md_files)} 个 Markdown 文件")
        
        success_count = 0
        fail_count = 0
        
        for md_file in md_files:
            success = process_md_file(
                md_path=md_file,
                access_token=access_token,
                cover_path=cover_path,
                auto_upload=args.upload
            )
            if success:
                success_count += 1
            else:
                fail_count += 1
        
        logger.info(f"处理完成：成功 {success_count} 个，失败 {fail_count} 个")
        
        if fail_count > 0:
            sys.exit(1)
    
    logger.info("所有任务完成！")


if __name__ == "__main__":
    main()
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
        
        # 3. 处理标题 (h1, h2, h3)
        if stripped.startswith('### '):
            content = stripped[4:].strip()
            html_parts.append(
                f'<h3 style="font-size: 17px; font-weight: bold; color: #2b2b2b; '
                f'margin: 1.2em 0 0.6em 0; line-height: 1.8;">{content}</h3>'
            )
            continue
        elif stripped.startswith('## '):
            content = stripped[3:].strip()
            html_parts.append(
                f'<h2 style="font-size: 18px; font-weight: bold; color: #2b2b2b; '
                f'margin: 1.5em 0 0.8em 0; line-height: 1.8; '
                f'border-bottom: 1px solid #e0e0e0; padding-bottom: 6px;">{content}</h2>'
            )
            continue
        elif stripped.startswith('# '):
            content = stripped[2:].strip()
            html_parts.append(
                f'<h1 style="font-size: 20px; font-weight: bold; color: #2b2b2b; '
                f'margin: 1.5em 0 0.8em 0; line-height: 1.8;">{content}</h1>'
            )
            continue
        
        # 4. 处理无序列表
        if stripped.startswith('- ') or stripped.startswith('* '):
            if in_ordered_list:
                html_parts.append('</ol>')
                in_ordered_list = False
                ordered_list_items = []
            if not in_list:
                html_parts.append('<ul style="padding-left: 2em; margin: 1em 0; list-style-type: disc;">')
                in_list = True
            content = stripped[2:].strip()
            html_parts.append(
                f'<li style="font-size: 17px; color: #2b2b2b; line-height: 1.8; margin: 0.3em 0;">{content}</li>'
            )
            continue
        
        # 5. 处理有序列表
        ordered_match = re.match(r'^(\d+)\.\s+(.*)', stripped)
        if ordered_match:
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            if not in_ordered_list:
                html_parts.append('<ol style="padding-left: 2em; margin: 1em 0; list-style-type: decimal;">')
                in_ordered_list = True
            num = ordered_match.group(1)
            content = ordered_match.group(2)
            html_parts.append(
                f'<li style="font-size: 17px; color: #2b2b2b; line-height: 1.8; margin: 0.3em 0;">'
                f'<span style="font-weight: bold; color: #07C160;">{num}.</span> {content}</li>'
            )
            continue
        
        # 6. 处理普通段落（包含内联样式）
        # 处理加粗 **text**
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        # 处理斜体 *text*
        line = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
        # 处理行内代码 `code`
        line = re.sub(r'`([^`]+)`', r'<code style="background-color: #f0f0f0; padding: 2px 4px; border-radius: 3px; font-size: 14px; color: #d63384;">\1</code>', line)
        # 处理链接 [text](url)
        line = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" style="color: #07C160; text-decoration: underline;">\1</a>', line)
        
        html_parts.append(
            f'<p style="font-size: 17px; color: #2b2b2b; line-height: 1.8; margin: 0.8em 0; word-wrap: break-word;">{line}</p>'
        )
    
    # 清理未关闭的标签
    if in_list:
        html_parts.append('</ul>')
    if in_ordered_list:
        html_parts.append('</ol>')
    if in_quote:
        quote_content = "<br/>".join(quote_lines)
        quote_content = remove_emoji(quote_content)
        html_parts.append(
            f'<blockquote style="background-color: #f5f5f5; border-left: 3px solid #07C160; '
            f'padding: 12px 16px; margin: 1.5em 0; color: #555; font-size: 16px; line-height: 1.7; '
            f'border-radius: 2px; word-wrap: break-word;">'
            f'{quote_content}</blockquote>'
        )
    
    return '\n'.join(html_parts)


def wrap_html_body(html_content: str) -> str:
    """
    将生成的 HTML 内容包裹在完整的微信公众号兼容模板中。
    包含基础样式重置和容器设置。
    """
    return f'''<section style="padding: 10px 16px; max-width: 677px; margin: 0 auto; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans SC', sans-serif;">
<div style="font-size: 17px; color: #2b2b2b; line-height: 1.8; letter-spacing: 0.5px;">
{html_content}
</div>
</section>'''


def read_md_file(file_path: str) -> Optional[str]:
    """读取 Markdown 文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"文件未找到: {file_path}")
        return None
    except Exception as e:
        logger.error(f"读取文件失败: {file_path}, 错误: {e}")
        return None


def save_html_output(html_content: str, output_path: str) -> bool:
    """保存生成的 HTML 到文件"""
    try:
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"HTML 文件已保存: {output_path}")
        return True
    except Exception as e:
        logger.error(f"保存 HTML 文件失败: {output_path}, 错误: {e}")
        return False


def upload_to_wechat_draft(
    title: str,
    html_content: str,
    cover_image_path: Optional[str] = None,
    author: str = "成都K12升学参谋",
    digest: str = ""
) -> bool:
    """
    将排版后的内容上传至微信公众号草稿箱。
    
    Args:
        title: 文章标题
        html_content: 排版后的 HTML 内容
        cover_image_path: 封面图片路径（可选）
        author: 作者名称
        digest: 文章摘要
    
    Returns:
        bool: 上传是否成功
    """
    try:
        # 获取 access_token
        access_token = get_access_token()
        if not access_token:
            logger.error("获取 access_token 失败")
            return False
        
        # 准备请求数据
        url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
        
        # 构建文章内容
        articles = []
        
        # 如果有封面图片，先上传图片获取 media_id
        thumb_media_id = None
        if cover_image_path and os.path.exists(cover_image_path):
            thumb_media_id = upload_image_to_wechat(access_token, cover_image_path)
            if not thumb_media_id:
                logger.warning("封面图片上传失败，将继续使用无封面的草稿")
        
        # 构建文章数据
        article = {
            "title": title,
            "author": author,
            "digest": digest or title[:120],
            "content": html_content,
            "need_open_comment": 1,
            "only_fans_can_comment": 0
        }
        
        if thumb_media_id:
            article["thumb_media_id"] = thumb_media_id
        
        articles.append(article)
        
        # 发送请求
        data = {
            "articles": articles
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=data)
            result = response.json()
            
            if result.get("errcode") == 0:
                media_id = result.get("media_id")
                logger.info(f"草稿上传成功！media_id: {media_id}")
                return True
            else:
                logger.error(f"草稿上传失败: {result.get('errmsg', '未知错误')}")
                return False
                
    except Exception as e:
        logger.error(f"上传草稿时发生异常: {e}")
        return False


def upload_image_to_wechat(access_token: str, image_path: str) -> Optional[str]:
    """
    上传图片到微信公众号素材库，获取 media_id。
    
    Args:
        access_token: 微信 access_token
        image_path: 图片文件路径
    
    Returns:
        Optional[str]: 图片的 media_id，失败返回 None
    """
    try:
        url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"
        
        with open(image_path, 'rb') as f:
            files = {'media': (os.path.basename(image_path), f, 'image/jpeg')}
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, files=files)
                result = response.json()
                
                if result.get("errcode") == 0:
                    media_id = result.get("media_id")
                    logger.info(f"图片上传成功，media_id: {media_id}")
                    return media_id
                else:
                    logger.error(f"图片上传失败: {result.get('errmsg', '未知错误')}")
                    return None
                    
    except Exception as e:
        logger.error(f"上传图片时发生异常: {e}")
        return None


def process_md_file(
    md_file_path: str,
    output_dir: str = "output",
    title: Optional[str] = None,
    author: str = "成都K12升学参谋",
    digest: str = "",
    cover_image: Optional[str] = None,
    auto_upload: bool = False
) -> bool:
    """
    处理单个 Markdown 文件：读取 -> 转换 -> 保存/上传
    
    Args:
        md_file_path: Markdown 文件路径
        output_dir: 输出目录
        title: 文章标题（默认使用文件名）
        author: 作者名称
        digest: 文章摘要
        cover_image: 封面图片路径
        auto_upload: 是否自动上传到微信公众号
    
    Returns:
        bool: 处理是否成功
    """
    # 读取 Markdown 文件
    md_content = read_md_file(md_file_path)
    if not md_content:
        return False
    
    # 转换 Markdown 为 HTML
    html_content = markdown_to_html(md_content)
    html_content = wrap_html_body(html_content)
    
    # 确定标题
    if not title:
        title = Path(md_file_path).stem
        # 移除文件名中的日期前缀（如 2024-01-15-）
        title = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', title)
        # 替换下划线为空格
        title = title.replace('_', ' ').replace('-', ' ')
    
    # 保存 HTML 文件
    output_path = Path(output_dir) / f"{Path(md_file_path).stem}.html"
    if not save_html_output(html_content, str(output_path)):
        return False
    
    # 自动上传到微信公众号
    if auto_upload:
        logger.info("开始上传到微信公众号草稿箱...")
        success = upload_to_wechat_draft(
            title=title,
            html_content=html_content,
            cover_image_path=cover_image,
            author=author,
            digest=digest
        )
        if success:
            logger.info("上传成功！")
        else:
            logger.error("上传失败！")
        return success
    
    return True


def batch_process(
    input_dir: str = "content",
    output_dir: str = "output",
    pattern: str = "*.md",
    auto_upload: bool = False,
    author: str = "成都K12升学参谋"
) -> int:
    """
    批量处理 content 目录下的 Markdown 文件
    
    Args:
        input_dir: 输入目录
        output_dir: 输出目录
        pattern: 文件匹配模式
        auto_upload: 是否自动上传
        author: 作者名称
    
    Returns:
        int: 成功处理的文件数量
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        logger.error(f"输入目录不存在: {input_dir}")
        return 0
    
    md_files = list(input_path.glob(pattern))
    if not md_files:
        logger.warning(f"在 {input_dir} 目录下未找到匹配 {pattern} 的文件")
        return 0
    
    logger.info(f"找到 {len(md_files)} 个 Markdown 文件")
    
    success_count = 0
    for md_file in md_files:
        logger.info(f"处理文件: {md_file}")
        try:
            if process_md_file(
                md_file_path=str(md_file),
                output_dir=output_dir,
                auto_upload=auto_upload,
                author=author
            ):
                success_count += 1
        except Exception as e:
            logger.error(f"处理文件 {md_file} 时出错: {e}")
    
    logger.info(f"处理完成，成功: {success_count}/{len(md_files)}")
    return success_count


def main():
    """主函数：解析命令行参数并执行"""
    parser = argparse.ArgumentParser(
        description="Markdown 转微信公众号富文本 HTML 排版工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 处理单个文件
  python scripts/md2wechat.py -f content/article.md
  
  # 批量处理 content 目录下所有 md 文件
  python scripts/md2wechat.py -b
  
  # 处理并自动上传到微信公众号
  python scripts/md2wechat.py -f content/article.md -u --title "文章标题" --cover cover.jpg
  
  # 指定自定义输出目录
  python scripts/md2wechat.py -f content/article.md -o my_output
        """
    )
    
    parser.add_argument(
        '-f', '--file',
        type=str,
        help='要处理的 Markdown 文件路径'
    )
    
    parser.add_argument(
        '-b', '--batch',
        action='store_true',
        help='批量处理 content 目录下的所有 Markdown 文件'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='output',
        help='输出目录 (默认: output)'
    )
    
    parser.add_argument(
        '-i', '--input',
        type=str,
        default='content',
        help='输入目录，用于批量处理 (默认: content)'
    )
    
    parser.add_argument(
        '-t', '--title',
        type=str,
        help='文章标题（默认使用文件名）'
    )
    
    parser.add_argument(
        '-a', '--author',
        type=str,
        default='成都K12升学参谋',
        help='作者名称 (默认: 成都K12升学参谋)'
    )
    
    parser.add_argument(
        '-d', '--digest',
        type=str,
        default='',
        help='文章摘要'
    )
    
    parser.add_argument(
        '-c', '--cover',
        type=str,
        help='封面图片路径'
    )
    
    parser.add_argument(
        '-u', '--upload',
        action='store_true',
        help='自动上传到微信公众号草稿箱'
    )
    
    parser.add_argument(
        '--pattern',
        type=str,
        default='*.md',
        help='批量处理时的文件匹配模式 (默认: *.md)'
    )
    
    args = parser.parse_args()
    
    # 确保输出目录存在
    Path(args.output).mkdir(parents=True, exist_ok=True)
    
    if args.batch:
        # 批量处理模式
        count = batch_process(
            input_dir=args.input,
            output_dir=args.output,
            pattern=args.pattern,
            auto_upload=args.upload,
            author=args.author
        )
        sys.exit(0 if count > 0 else 1)
    
    elif args.file:
        # 单文件处理模式
        success = process_md_file(
            md_file_path=args.file,
            output_dir=args.output,
            title=args.title,
            author=args.author,
            digest=args.digest,
            cover_image=args.cover,
            auto_upload=args.upload
        )
        sys.exit(0 if success else 1)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
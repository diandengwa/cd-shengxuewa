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
            
        # 3. 忽略一级标题 (微信草稿有独立的标题字段，正文里重复显示会显得冗余)
        if stripped.startswith('# '):
            continue
            
        # 4. 处理二级标题 <h2>
        if stripped.startswith('## '):
            title_text = stripped[3:].strip()
            # 处理标题中的加粗/斜体
            title_text = _process_inline_formatting(title_text)
            html_parts.append(
                f'<h2 style="font-size: 18px; font-weight: bold; color: #2b2b2b; '
                f'margin: 1.5em 0 0.8em 0; padding-bottom: 8px; '
                f'border-bottom: 1px solid #e8e8e8;">{title_text}</h2>'
            )
            continue
            
        # 5. 处理三级标题 <h3>
        if stripped.startswith('### '):
            title_text = stripped[4:].strip()
            title_text = _process_inline_formatting(title_text)
            html_parts.append(
                f'<h3 style="font-size: 17px; font-weight: bold; color: #2b2b2b; '
                f'margin: 1.2em 0 0.6em 0;">{title_text}</h3>'
            )
            continue
            
        # 6. 处理无序列表 <ul><li>
        if stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                in_list = True
                html_parts.append('<ul style="padding-left: 2em; margin: 1em 0;">')
            item_content = stripped[2:].strip()
            item_content = _process_inline_formatting(item_content)
            html_parts.append(
                f'<li style="font-size: 17px; line-height: 1.8; color: #2b2b2b; '
                f'margin-bottom: 0.3em;">{item_content}</li>'
            )
            continue
        else:
            if in_list:
                html_parts.append('</ul>')
                in_list = False
                
        # 7. 处理有序列表 <ol><li>
        ordered_match = re.match(r'^(\d+)\.\s+(.*)', stripped)
        if ordered_match:
            if not in_ordered_list:
                in_ordered_list = True
                ordered_list_items = []
            item_content = ordered_match.group(2).strip()
            item_content = _process_inline_formatting(item_content)
            ordered_list_items.append(item_content)
            continue
        else:
            if in_ordered_list and ordered_list_items:
                html_parts.append('<ol style="padding-left: 2em; margin: 1em 0;">')
                for item in ordered_list_items:
                    html_parts.append(
                        f'<li style="font-size: 17px; line-height: 1.8; color: #2b2b2b; '
                        f'margin-bottom: 0.3em;">{item}</li>'
                    )
                html_parts.append('</ol>')
                in_ordered_list = False
                ordered_list_items = []
        
        # 8. 处理图片 ![alt](url)
        img_match = re.match(r'!\[(.*?)\]\((.*?)\)', stripped)
        if img_match:
            alt_text = img_match.group(1)
            img_url = img_match.group(2)
            html_parts.append(
                f'<img src="{img_url}" alt="{alt_text}" style="max-width: 100%; '
                f'height: auto; margin: 1em 0; border-radius: 4px; display: block;" />'
            )
            continue
            
        # 9. 处理普通段落
        paragraph = _process_inline_formatting(stripped)
        html_parts.append(
            f'<p style="font-size: 17px; line-height: 1.8; color: #2b2b2b; '
            f'margin: 0.8em 0; word-wrap: break-word;">{paragraph}</p>'
        )
    
    # 清理未关闭的标签
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
    
    if in_ordered_list and ordered_list_items:
        html_parts.append('<ol style="padding-left: 2em; margin: 1em 0;">')
        for item in ordered_list_items:
            html_parts.append(
                f'<li style="font-size: 17px; line-height: 1.8; color: #2b2b2b; '
                f'margin-bottom: 0.3em;">{item}</li>'
            )
        html_parts.append('</ol>')
    
    if in_code_block:
        # 未关闭的代码块，直接输出
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


def _process_inline_formatting(text: str) -> str:
    """
    处理行内格式：加粗、斜体、行内代码、链接
    """
    # 先处理行内代码 `code`
    text = re.sub(r'`([^`]+)`', r'<code style="background-color: #f0f0f0; padding: 2px 6px; '
                 r'border-radius: 3px; font-size: 15px; color: #d63384; '
                 r'font-family: Consolas, Monaco, monospace;">\1</code>', text)
    
    # 处理加粗 **text** 或 __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
    
    # 处理斜体 *text* 或 _text_
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)
    
    # 处理链接 [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', 
                  r'<a href="\2" style="color: #07C160; text-decoration: none;">\1</a>', text)
    
    return text


def extract_title_and_cover(md_text: str, md_file: Path) -> tuple:
    """
    从 Markdown 中提取标题和封面图路径
    - 标题：第一个 # 开头的行
    - 封面图：第一个 ![](url) 或 <!-- cover: url --> 注释
    """
    title = ""
    cover_url = ""
    
    lines = md_text.splitlines()
    for line in lines:
        stripped = line.strip()
        
        # 提取标题
        if not title and stripped.startswith('# '):
            title = stripped[2:].strip()
            
        # 提取封面图（优先使用 <!-- cover: url --> 注释）
        cover_match = re.match(r'<!--\s*cover:\s*(.+?)\s*-->', stripped)
        if cover_match:
            cover_url = cover_match.group(1).strip()
            
        # 如果没有 cover 注释，使用第一个图片
        if not cover_url:
            img_match = re.match(r'!\[.*?\]\((.+?)\)', stripped)
            if img_match:
                cover_url = img_match.group(1)
    
    # 如果还是没有标题，使用文件名
    if not title:
        title = md_file.stem.replace('-', ' ').replace('_', ' ').title()
    
    return title, cover_url


def upload_draft_to_wechat(
    access_token: str,
    title: str,
    html_content: str,
    cover_media_id: Optional[str] = None,
    digest: Optional[str] = None,
    author: str = "点灯蛙·成都K12升学参谋"
) -> Dict[str, Any]:
    """
    上传图文草稿到微信公众号
    """
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
    
    # 构建文章内容
    article = {
        "title": title,
        "content": html_content,
        "need_open_comment": 1,
        "only_fans_can_comment": 0,
        "author": author,
    }
    
    if cover_media_id:
        article["thumb_media_id"] = cover_media_id
    
    if digest:
        article["digest"] = digest
    else:
        # 自动生成摘要：取前120个字符
        plain_text = re.sub(r'<[^>]+>', '', html_content)
        plain_text = re.sub(r'\s+', ' ', plain_text).strip()
        article["digest"] = plain_text[:120]
    
    payload = {
        "articles": [article]
    }
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            result = response.json()
            
            if result.get("errcode") == 0:
                logger.info(f"✅ 草稿上传成功，media_id: {result.get('media_id')}")
                return result
            else:
                logger.error(f"❌ 草稿上传失败: {result.get('errmsg', '未知错误')}")
                return result
    except Exception as e:
        logger.error(f"❌ 上传请求异常: {str(e)}")
        return {"errcode": -1, "errmsg": str(e)}


def upload_image_to_wechat(access_token: str, image_path: Path) -> Optional[str]:
    """
    上传图片到微信公众号，返回 media_id
    """
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"
    
    if not image_path.exists():
        logger.error(f"❌ 图片文件不存在: {image_path}")
        return None
    
    try:
        with httpx.Client(timeout=60.0) as client:
            with open(image_path, "rb") as f:
                files = {"media": (image_path.name, f, "image/jpeg")}
                response = client.post(url, files=files)
                result = response.json()
                
                if result.get("errcode") == 0:
                    logger.info(f"✅ 图片上传成功，media_id: {result.get('media_id')}")
                    return result.get("media_id")
                else:
                    logger.error(f"❌ 图片上传失败: {result.get('errmsg', '未知错误')}")
                    return None
    except Exception as e:
        logger.error(f"❌ 图片上传异常: {str(e)}")
        return None


def process_md_file(
    md_file: Path,
    access_token: Optional[str] = None,
    upload: bool = False,
    output_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    处理单个 Markdown 文件
    """
    logger.info(f"📄 处理文件: {md_file}")
    
    # 读取 Markdown 内容
    try:
        with open(md_file, "r", encoding="utf-8") as f:
            md_text = f.read()
    except Exception as e:
        logger.error(f"❌ 读取文件失败: {str(e)}")
        return {"success": False, "error": str(e)}
    
    # 提取标题和封面图
    title, cover_url = extract_title_and_cover(md_text, md_file)
    logger.info(f"📝 标题: {title}")
    if cover_url:
        logger.info(f"🖼️ 封面图: {cover_url}")
    
    # 转换为 HTML
    html_content = markdown_to_html(md_text)
    
    # 保存 HTML 到文件
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        html_file = output_dir / f"{md_file.stem}.html"
        try:
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"💾 HTML 已保存: {html_file}")
        except Exception as e:
            logger.error(f"❌ 保存 HTML 失败: {str(e)}")
    
    # 上传到微信公众号
    if upload and access_token:
        # 上传封面图
        cover_media_id = None
        if cover_url:
            cover_path = Path(cover_url)
            if not cover_path.is_absolute():
                cover_path = md_file.parent / cover_path
            if cover_path.exists():
                cover_media_id = upload_image_to_wechat(access_token, cover_path)
            else:
                logger.warning(f"⚠️ 封面图文件不存在: {cover_path}")
        
        # 上传草稿
        result = upload_draft_to_wechat(
            access_token=access_token,
            title=title,
            html_content=html_content,
            cover_media_id=cover_media_id
        )
        
        if result.get("errcode") == 0:
            return {
                "success": True,
                "title": title,
                "media_id": result.get("media_id"),
                "html_content": html_content
            }
        else:
            return {
                "success": False,
                "title": title,
                "error": result.get("errmsg", "上传失败"),
                "html_content": html_content
            }
    
    return {
        "success": True,
        "title": title,
        "html_content": html_content
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Markdown 转微信公众号富文本 HTML 排版工具"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="要处理的 Markdown 文件路径（支持通配符）"
    )
    parser.add_argument(
        "-d", "--directory",
        default="content",
        help="Markdown 文件所在目录（默认: content）"
    )
    parser.add_argument(
        "-o", "--output",
        default="output",
        help="HTML 输出目录（默认: output）"
    )
    parser.add_argument(
        "-u", "--upload",
        action="store_true",
        help="上传到微信公众号草稿箱"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="不保存 HTML 文件"
    )
    
    args = parser.parse_args()
    
    # 确定要处理的文件列表
    md_files = []
    if args.files:
        for pattern in args.files:
            md_files.extend(Path().glob(pattern))
    else:
        content_dir = Path(args.directory)
        if content_dir.exists():
            md_files = list(content_dir.glob("*.md"))
    
    if not md_files:
        logger.warning("⚠️ 没有找到 Markdown 文件")
        return
    
    logger.info(f"📚 找到 {len(md_files)} 个 Markdown 文件")
    
    # 获取 access_token（如果需要上传）
    access_token = None
    if args.upload:
        try:
            access_token = get_access_token()
            logger.info("🔑 获取 access_token 成功")
        except Exception as e:
            logger.error(f"❌ 获取 access_token 失败: {str(e)}")
            return
    
    # 输出目录
    output_dir = None if args.no_save else Path(args.output)
    
    # 处理每个文件
    success_count = 0
    fail_count = 0
    
    for md_file in md_files:
        result = process_md_file(
            md_file=md_file,
            access_token=access_token,
            upload=args.upload,
            output_dir=output_dir
        )
        
        if result["success"]:
            success_count += 1
            logger.info(f"✅ 处理成功: {result['title']}")
        else:
            fail_count += 1
            logger.error(f"❌ 处理失败: {result.get('title', md_file.name)} - {result.get('error', '未知错误')}")
    
    # 输出统计信息
    logger.info(f"\n📊 处理完成: 成功 {success_count} 个, 失败 {fail_count} 个")
    
    if args.upload:
        logger.info("🚀 已上传到微信公众号草稿箱")


if __name__ == "__main__":
    main()
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
            continue
            
        # 3. 忽略一级标题 (微信草稿有独立的标题字段，正文里重复显示会显得冗余)
        if stripped.startswith('# '):
            continue
            
        # 4. 处理二级标题 <h2>
        if stripped.startswith('## '):
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            title_text = stripped[3:].strip()
            # 剥离可能存在的 markdown 加粗标记
            title_text = re.sub(r'\*\*(.*?)\*\*', r'\1', title_text)
            html_parts.append(
                f'<h2 style="font-size: 19px; font-weight: bold; color: #2b2b2b; '
                f'margin: 1.6em 0 0.8em 0; border-bottom: 1px solid #eef0f2; padding-bottom: 6px; '
                f'display: block; line-height: 1.4;">'
                f'{title_text}</h2>'
            )
            continue
            
        # 5. 处理无序列表 <ul>
        if stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                html_parts.append('<ul style="padding-left: 20px; margin: 1.2em 0; color: #2b2b2b; list-style-type: disc;">')
                in_list = True
            item_text = stripped[2:].strip()
            item_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item_text)
            html_parts.append(f'<li style="font-size: 17px; line-height: 1.8; margin-bottom: 0.6em;">{item_text}</li>')
            continue
        
        # 6. 处理有序列表 <ol>
        if re.match(r'^\d+\.\s', stripped):
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            # 提取序号和内容
            match = re.match(r'^(\d+)\.\s(.*)', stripped)
            if match:
                num = match.group(1)
                item_text = match.group(2)
                item_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item_text)
                html_parts.append(
                    f'<p style="font-size: 17px; line-height: 1.8; margin: 0.8em 0; color: #2b2b2b;">'
                    f'<span style="font-weight: bold; color: #07C160;">{num}.</span> {item_text}</p>'
                )
            continue
        
        # 7. 处理普通段落
        if in_list:
            html_parts.append('</ul>')
            in_list = False
        
        # 处理行内样式：加粗、斜体、链接
        paragraph = stripped
        paragraph = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', paragraph)
        paragraph = re.sub(r'\*(.*?)\*', r'<em>\1</em>', paragraph)
        paragraph = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" style="color: #07C160; text-decoration: none;">\1</a>', paragraph)
        
        html_parts.append(
            f'<p style="font-size: 17px; line-height: 1.8; margin: 0.8em 0; color: #2b2b2b;">'
            f'{paragraph}</p>'
        )
    
    # 处理未关闭的标签
    if in_list:
        html_parts.append('</ul>')
    if in_quote:
        quote_content = "<br/>".join(quote_lines)
        quote_content = remove_emoji(quote_content)
        html_parts.append(
            f'<blockquote style="background-color: #f5f5f5; border-left: 3px solid #07C160; '
            f'padding: 12px 16px; margin: 1.5em 0; color: #555; font-size: 16px; line-height: 1.7; '
            f'border-radius: 2px; word-wrap: break-word;">'
            f'{quote_content}</blockquote>'
        )
    if in_code_block:
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


def extract_title_from_md(md_text: str) -> Optional[str]:
    """从 Markdown 文本中提取第一个一级标题作为文章标题"""
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith('# '):
            return stripped[2:].strip()
    return None


def extract_cover_image(md_text: str, md_file_path: Path) -> Optional[str]:
    """
    从 Markdown 文本中提取封面图路径。
    优先查找 ![](image.jpg) 格式的图片引用，然后查找本地文件。
    返回图片的绝对路径或 URL。
    """
    # 查找 Markdown 图片语法
    img_pattern = re.compile(r'!\[.*?\]\((.*?)\)')
    matches = img_pattern.findall(md_text)
    
    for img_path in matches:
        # 如果是相对路径，基于 md 文件所在目录解析
        if not img_path.startswith(('http://', 'https://')):
            abs_path = md_file_path.parent / img_path
            if abs_path.exists():
                return str(abs_path)
        else:
            return img_path
    
    # 查找 content/images/ 目录下同名图片
    md_stem = md_file_path.stem
    images_dir = root_dir / "content" / "images"
    if images_dir.exists():
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            cover_path = images_dir / f"{md_stem}{ext}"
            if cover_path.exists():
                return str(cover_path)
    
    return None


def upload_image_to_wechat(access_token: str, image_path: str) -> Optional[str]:
    """
    上传图片到微信公众号素材库，返回图片的 media_id。
    用于封面图和正文中的图片。
    """
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"
    
    try:
        with open(image_path, 'rb') as f:
            files = {'media': (os.path.basename(image_path), f, 'image/jpeg')}
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, files=files)
                result = response.json()
                
                if 'media_id' in result:
                    logger.info(f"图片上传成功: {image_path} -> media_id: {result['media_id']}")
                    return result['media_id']
                else:
                    logger.error(f"图片上传失败: {result}")
                    return None
    except Exception as e:
        logger.error(f"图片上传异常: {e}")
        return None


def create_draft(access_token: str, title: str, html_content: str, 
                 cover_media_id: Optional[str] = None, 
                 digest: Optional[str] = None) -> Optional[str]:
    """
    创建微信公众号草稿。
    返回草稿的 media_id。
    """
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
    
    # 构建文章内容
    article = {
        "title": title,
        "content": html_content,
        "need_open_comment": 1,
        "only_fans_can_comment": 0,
    }
    
    if cover_media_id:
        article["thumb_media_id"] = cover_media_id
    
    if digest:
        article["digest"] = digest[:120]  # 微信限制摘要长度
    
    payload = {
        "articles": [article]
    }
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            result = response.json()
            
            if 'media_id' in result:
                logger.info(f"草稿创建成功: {title} -> media_id: {result['media_id']}")
                return result['media_id']
            else:
                logger.error(f"草稿创建失败: {result}")
                return None
    except Exception as e:
        logger.error(f"草稿创建异常: {e}")
        return None


def process_md_file(md_path: Path, upload: bool = False, 
                    cover_image: Optional[str] = None) -> Dict[str, Any]:
    """
    处理单个 Markdown 文件，生成 HTML 并可选上传到微信公众号。
    
    参数:
        md_path: Markdown 文件路径
        upload: 是否上传到微信公众号
        cover_image: 封面图路径（可选）
    
    返回:
        包含处理结果的字典
    """
    result = {
        "file": str(md_path),
        "success": False,
        "title": None,
        "html": None,
        "draft_media_id": None,
        "error": None
    }
    
    try:
        # 读取 Markdown 文件
        with open(md_path, 'r', encoding='utf-8') as f:
            md_text = f.read()
        
        # 提取标题
        title = extract_title_from_md(md_text)
        if not title:
            # 使用文件名作为标题
            title = md_path.stem.replace('-', ' ').replace('_', ' ').title()
        
        # 转换为 HTML
        html_content = markdown_to_html(md_text)
        
        # 包装完整的 HTML 文档
        full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; padding: 0; margin: 0;">
    <div style="max-width: 100%; padding: 10px 15px;">
        {html_content}
    </div>
</body>
</html>"""
        
        result["title"] = title
        result["html"] = full_html
        
        # 如果需要上传到微信公众号
        if upload:
            # 获取 access_token
            access_token = get_access_token()
            if not access_token:
                result["error"] = "获取 access_token 失败"
                return result
            
            # 处理封面图
            cover_media_id = None
            if cover_image:
                cover_media_id = upload_image_to_wechat(access_token, cover_image)
            else:
                # 尝试自动查找封面图
                auto_cover = extract_cover_image(md_text, md_path)
                if auto_cover:
                    cover_media_id = upload_image_to_wechat(access_token, auto_cover)
            
            # 生成摘要（取前120个字符）
            digest = re.sub(r'<[^>]+>', '', html_content)[:120]
            
            # 创建草稿
            draft_media_id = create_draft(
                access_token=access_token,
                title=title,
                html_content=full_html,
                cover_media_id=cover_media_id,
                digest=digest
            )
            
            if draft_media_id:
                result["draft_media_id"] = draft_media_id
                result["success"] = True
                logger.info(f"成功处理并上传: {md_path.name}")
            else:
                result["error"] = "创建草稿失败"
        else:
            result["success"] = True
            logger.info(f"成功处理（仅排版）: {md_path.name}")
    
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"处理文件失败 {md_path}: {e}")
    
    return result


def process_directory(directory: Path, upload: bool = False,
                      cover_image: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    处理目录下所有 Markdown 文件。
    """
    results = []
    md_files = sorted(directory.glob("*.md"))
    
    if not md_files:
        logger.warning(f"目录 {directory} 中没有找到 Markdown 文件")
        return results
    
    logger.info(f"找到 {len(md_files)} 个 Markdown 文件")
    
    for md_file in md_files:
        logger.info(f"处理文件: {md_file.name}")
        result = process_md_file(md_file, upload=upload, cover_image=cover_image)
        results.append(result)
    
    return results


def save_html_output(html_content: str, output_path: Path) -> None:
    """保存 HTML 到文件"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    logger.info(f"HTML 已保存到: {output_path}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Markdown 转微信公众号富文本 HTML 排版工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 仅排版，输出 HTML 到 output/ 目录
  python scripts/md2wechat.py content/article.md
  
  # 排版并上传到微信公众号草稿箱
  python scripts/md2wechat.py content/article.md --upload
  
  # 处理整个目录
  python scripts/md2wechat.py content/ --upload
  
  # 指定封面图
  python scripts/md2wechat.py content/article.md --upload --cover images/cover.jpg
  
  # 输出到指定目录
  python scripts/md2wechat.py content/article.md --output-dir ./output
        """
    )
    
    parser.add_argument(
        "input",
        help="输入的 Markdown 文件或目录路径"
    )
    parser.add_argument(
        "--upload", "-u",
        action="store_true",
        help="上传到微信公众号草稿箱"
    )
    parser.add_argument(
        "--cover", "-c",
        help="封面图路径（可选）"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output",
        help="HTML 输出目录（默认: output）"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细日志输出"
    )
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    
    # 处理封面图路径
    cover_path = None
    if args.cover:
        cover_path = Path(args.cover)
        if not cover_path.exists():
            logger.error(f"封面图不存在: {cover_path}")
            sys.exit(1)
        cover_path = str(cover_path)
    
    # 处理输入
    if input_path.is_file():
        # 处理单个文件
        if input_path.suffix.lower() not in ['.md', '.markdown']:
            logger.error(f"不支持的文件格式: {input_path.suffix}")
            sys.exit(1)
        
        result = process_md_file(input_path, upload=args.upload, cover_image=cover_path)
        
        if result["success"] and result["html"]:
            # 保存 HTML 输出
            output_file = output_dir / f"{input_path.stem}.html"
            save_html_output(result["html"], output_file)
            
            # 输出结果摘要
            print(f"\n✅ 处理完成: {input_path.name}")
            print(f"   标题: {result['title']}")
            print(f"   HTML: {output_file}")
            if result["draft_media_id"]:
                print(f"   草稿 media_id: {result['draft_media_id']}")
        else:
            print(f"\n❌ 处理失败: {result.get('error', '未知错误')}")
            sys.exit(1)
    
    elif input_path.is_dir():
        # 处理目录
        results = process_directory(input_path, upload=args.upload, cover_image=cover_path)
        
        # 保存所有 HTML 输出
        success_count = 0
        for result in results:
            if result["success"] and result["html"]:
                output_file = output_dir / f"{Path(result['file']).stem}.html"
                save_html_output(result["html"], output_file)
                success_count += 1
                
                print(f"✅ {Path(result['file']).name}: {result['title']}")
                if result["draft_media_id"]:
                    print(f"   草稿 media_id: {result['draft_media_id']}")
            else:
                print(f"❌ {Path(result['file']).name}: {result.get('error', '未知错误')}")
        
        print(f"\n📊 处理统计: 成功 {success_count}/{len(results)}")
    
    else:
        logger.error(f"输入路径不存在: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
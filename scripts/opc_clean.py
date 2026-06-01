#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OPC 文章清洗脚本 - 清除微信公众号文章中的CSS/HTML噪声
- 移除开头的CSS样式块
- 移除Markdown中的转义噪声
- 保留文章正文和图片引用
- 处理指定日期目录下所有文章，或单个文件
"""

import re
import sys
import os
from pathlib import Path
from datetime import datetime

RAW_DIR = Path(r"D:\opc\raw-articles")
LOG_DIR = Path(r"D:\opc\pipeline-logs")

# CSS噪声的正则模式 - 文章开头的样式代码块
CSS_BLOCK_PATTERN = re.compile(
    r'^\s*#[a-zA-Z_][\w\-]*\s*\{[^}]*\}'   # #selector { ... }
    r'|^\s*\.[a-zA-Z_][\w\-]*\s*\{[^}]*\}'  # .class { ... }
    r'|^\s*\.[a-zA-Z_][\w\-]*::?[\w\-]*\s*\{[^}]*\}'  # .class::before { ... }
    r'|^\s*#[a-zA-Z_][\w\-]*\s+\.[a-zA-Z_][\w\-]*\s*\{[^}]*\}',  # #id .class { ... }
    re.MULTILINE
)

# 整行CSS噪声（通常是一大行包含多个CSS规则）
CSS_INLINE_PATTERN = re.compile(
    r'^\s*#js_\w+\s*\{.*?\}'           # #js_xxx { ... }
    r'|^\s*\.\w+\s*\{.*?\}'            # .xxx { ... }
    r'|^\s*#\w+\s*\.\w+\s*\{.*?\}'     # #xxx .yyy { ... }
    r'|^\s*#\w+\s+\.\w+\s*\{.*?\}'     # #xxx .yyy { ... }
)

# 微信阅读器噪声行
WECHAT_NOISE_PATTERNS = [
    re.compile(r'^\[在小说阅读器读本章\]', re.IGNORECASE),
    re.compile(r'^去阅读\s*$', re.IGNORECASE),
    re.compile(r'^在小说阅读器中沉浸阅读\s*$', re.IGNORECASE),
    re.compile(r'^\[.*?\]\(javascript:void\\?\(0\);\)\s*$', re.IGNORECASE),  # [xxx](javascript:void(0);)
    re.compile(r'^\s*$', re.IGNORECASE),  # 空行（保留一个）
]

# Markdown转义修复
ESCAPE_FIX_PATTERNS = [
    (re.compile(r'\\_'), '_'),           # \_ → _
    (re.compile(r'\\_'), '_'),           # 二次修复
    (re.compile(r'\(\\?0\\?\)'), ''),     # (0) 结尾噪声
]


def clean_css_block(text: str) -> str:
    """移除文章开头的CSS样式块"""
    lines = text.split('\n')
    cleaned_lines = []
    in_frontmatter = False
    frontmatter_count = 0
    past_frontmatter = False
    css_ended = False
    
    for i, line in enumerate(lines):
        # 跳过frontmatter
        if line.strip() == '---':
            frontmatter_count += 1
            if frontmatter_count <= 2:
                in_frontmatter = True
                cleaned_lines.append(line)
                continue
        
        if in_frontmatter and frontmatter_count < 2:
            cleaned_lines.append(line)
            continue
        
        if frontmatter_count >= 2:
            in_frontmatter = False
            past_frontmatter = True
        
        if past_frontmatter and not css_ended:
            # 检查是否是CSS行
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue
            
            # CSS行特征：包含CSS选择器和属性
            if (re.match(r'^\s*#[\w\-]+.*\{.*\}', stripped) or
                re.match(r'^\s*\.[\w\-]+.*\{.*\}', stripped) or
                re.match(r'^\s*#[\w\-]+\s+\.[\w\-]+.*\{.*\}', stripped) or
                'max-width:' in stripped or 'margin:' in stripped or
                'display:' in stripped or 'width:' in stripped or
                'border-radius:' in stripped or 'padding:' in stripped or
                'background:' in stripped or 'font-size:' in stripped or
                'line-height:' in stripped or 'text-align:' in stripped or
                'overflow:' in stripped or 'position:' in stripped or
                ('::before' in stripped and '{' in stripped) or
                ('::after' in stripped and '{' in stripped)):
                continue  # 跳过CSS行
            
            # 如果遇到了标题行（通常是 === 下划线式标题或 # 标题），CSS已结束
            if (re.match(r'^=+\s*$', stripped) or 
                re.match(r'^-+\s*$', stripped) or
                re.match(r'^#+\s+\S', stripped) or
                re.match(r'^!\[', stripped) or  # 图片
                re.match(r'^\[', stripped) or    # 链接
                len(stripped) > 5 and not any(c in stripped for c in '{}:;')):
                css_ended = True
                cleaned_lines.append(line)
                continue
            
            # 其他短行可能是CSS噪声
            if len(stripped) < 5 and any(c in stripped for c in '{}:;'):
                continue
            
            css_ended = True
            cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)


def clean_noise_lines(text: str) -> str:
    """移除微信阅读器噪声行"""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # 移除javascript:void链接
        if 'javascript:void' in stripped:
            # 但保留有用的链接文本
            if re.match(r'^\[.*?\]\(javascript:void', stripped):
                # 提取文本
                m = re.match(r'^\[(.*?)\]\(javascript:void.*', stripped)
                if m and m.group(1).strip():
                    cleaned.append(m.group(1).strip())
                continue
        # 移除"在小说阅读器"噪声
        if re.match(r'^在小说阅读器', stripped):
            continue
        if stripped == '去阅读':
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def fix_escapes(text: str) -> str:
    """修复Markdown转义"""
    result = text
    for pattern, replacement in ESCAPE_FIX_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def clean_article(content: str) -> str:
    """完整的文章清洗流程"""
    # 1. 清除CSS块
    result = clean_css_block(content)
    # 2. 清除噪声行
    result = clean_noise_lines(result)
    # 3. 修复转义
    result = fix_escapes(result)
    # 4. 合并多余空行（最多保留2个连续空行）
    result = re.sub(r'\n{4,}', '\n\n\n', result)
    # 5. 移除首尾空白
    result = result.strip() + '\n'
    return result


def process_file(filepath: Path, dry_run: bool = False) -> tuple[bool, str]:
    """处理单个文件，返回 (是否修改, 消息)"""
    try:
        original = filepath.read_text(encoding='utf-8-sig')
    except Exception:
        try:
            original = filepath.read_text(encoding='utf-8')
        except Exception as e:
            return False, f"读取失败: {e}"
    
    cleaned = clean_article(original)
    
    if cleaned == original:
        return False, "无需清洗"
    
    size_before = len(original)
    size_after = len(cleaned)
    reduction = size_before - size_after
    
    if not dry_run:
        filepath.write_text(cleaned, encoding='utf-8')
    
    return True, f"清洗完成: {size_before}→{size_after}字节 (减少{reduction}字节)"


def process_directory(date_dir: Path, dry_run: bool = False) -> dict:
    """处理指定日期目录下的所有文章"""
    stats = {
        'total': 0,
        'cleaned': 0,
        'skipped': 0,
        'errors': 0,
        'bytes_saved': 0,
    }
    
    md_files = sorted(date_dir.rglob('*.md'))
    stats['total'] = len(md_files)
    
    print(f"发现 {len(md_files)} 个.md文件")
    
    for i, filepath in enumerate(md_files, 1):
        rel_path = filepath.relative_to(date_dir)
        modified, msg = process_file(filepath, dry_run)
        
        if '失败' in msg:
            stats['errors'] += 1
            print(f"  [{i}/{len(md_files)}] X {rel_path}: {msg}")
        elif modified:
            stats['cleaned'] += 1
            size_diff = filepath.stat().st_size if not dry_run else 0
            print(f"  [{i}/{len(md_files)}] OK {rel_path}: {msg}")
        else:
            stats['skipped'] += 1
            if i % 100 == 0:
                print(f"  [{i}/{len(md_files)}] ... processed {stats['cleaned']} so far")
    
    return stats


def main():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    import argparse
    parser = argparse.ArgumentParser(description='OPC文章CSS噪声清洗')
    parser.add_argument('--date', default=None, help='指定日期(YYYY-MM-DD)，默认今天')
    parser.add_argument('--all', action='store_true', help='处理所有日期目录')
    parser.add_argument('--dry-run', action='store_true', help='仅预览不修改')
    parser.add_argument('--file', default=None, help='处理单个文件')
    args = parser.parse_args()
    
    if args.file:
        filepath = Path(args.file)
        if not filepath.exists():
            print(f"文件不存在: {filepath}")
            return 1
        modified, msg = process_file(filepath, args.dry_run)
        print(f"{filepath.name}: {msg}")
        return 0
    
    if args.all:
        dirs = sorted(RAW_DIR.iterdir())
    else:
        date = args.date or datetime.now().strftime('%Y-%m-%d')
        target = RAW_DIR / date
        if not target.exists():
            print(f"目录不存在: {target}")
            return 1
        dirs = [target]
    
    total_stats = {'total': 0, 'cleaned': 0, 'skipped': 0, 'errors': 0, 'bytes_saved': 0}
    
    for d in dirs:
        if not d.is_dir():
            continue
        print(f"\n{'='*60}")
        print(f"处理目录: {d.name}")
        print(f"{'='*60}")
        
        stats = process_directory(d, args.dry_run)
        for k in total_stats:
            total_stats[k] += stats.get(k, 0)
    
    print(f"\n{'='*60}")
    print(f"总计: {total_stats['total']}篇 | 清洗{total_stats['cleaned']}篇 | 跳过{total_stats['skipped']}篇 | 错误{total_stats['errors']}篇")
    if args.dry_run:
        print("(dry-run模式，未实际修改文件)")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

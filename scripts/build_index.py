#!/usr/bin/env python3
"""
构建轻量索引
从 wiki/ 目录生成 manifest.json 和 search_index.json
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
WIKI_DIR = PROJECT_ROOT / "wiki"
BUILD_DIR = PROJECT_ROOT / "build"


def extract_frontmatter(content: str) -> dict:
    """从 Markdown 内容提取基本信息"""
    info = {
        "title": "",
        "year": "",
        "stage": "",
        "region": "",
        "source_grade": "",
    }

    # 提取标题（第一个 # 开头的行）
    title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if title_match:
        info["title"] = title_match.group(1).strip()

    # 提取适用年份
    year_match = re.search(r'\*\*适用年份\*\*:\s*(\d{4})', content)
    if year_match:
        info["year"] = year_match.group(1)

    # 提取学段
    stage_match = re.search(r'\*\*学段\*\*:\s*(.+?)(?:\n|$)', content)
    if stage_match:
        info["stage"] = stage_match.group(1).strip()

    # 提取区域
    region_match = re.search(r'\*\*区域\*\*:\s*(.+?)(?:\n|$)', content)
    if region_match:
        info["region"] = region_match.group(1).strip()

    # 提取可信等级
    grade_match = re.search(r'\*\*可信等级\*\*\s*\n?\s*(S|A|B|C|D)', content)
    if grade_match:
        info["source_grade"] = grade_match.group(1)

    return info


def extract_keywords(content: str) -> list:
    """提取关键词"""
    keywords = set()

    # 从标题提取
    title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if title_match:
        title = title_match.group(1)
        keywords.update(title.replace('—', ' ').replace('-', ' ').split())

    # 从核心结论提取关键词
    conclusion_match = re.search(r'## 核心结论\s*\n(.+?)(?=##|\Z)', content, re.DOTALL)
    if conclusion_match:
        conclusion = conclusion_match.group(1)
        # 提取重要名词
        important_terms = [
            '户籍', '随迁', '积分', '材料', '社保', '居住证',
            '划片', '电脑随机', '民办', '公办', '市直属',
            '信息采集', '学位', '入学', '招生', '录取',
            '幼儿园', '小学', '初中', '高中', '中考',
            '青羊', '锦江', '金牛', '武侯', '成华', '高新', '天府',
        ]
        for term in important_terms:
            if term in conclusion:
                keywords.add(term)

    return list(keywords)


def get_page_type(rel_path: str) -> str:
    """根据路径判断页面类型"""
    if 'scenarios/' in rel_path:
        return 'scenario'
    elif 'policies/' in rel_path:
        return 'policy'
    elif 'districts/' in rel_path:
        return 'district'
    elif 'reference/' in rel_path:
        return 'reference'
    elif 'faq/' in rel_path:
        return 'faq'
    elif 'assessment_templates/' in rel_path:
        return 'template'
    return 'other'


def build_manifest() -> list:
    """构建页面清单"""
    manifest = []

    for md_file in sorted(WIKI_DIR.rglob('*.md')):
        rel_path = md_file.relative_to(PROJECT_ROOT).as_posix()

        # 跳过 README
        if md_file.name == 'README.md':
            continue

        content = md_file.read_text(encoding='utf-8')
        info = extract_frontmatter(content)
        page_type = get_page_type(rel_path)
        keywords = extract_keywords(content)

        entry = {
            "path": rel_path,
            "type": page_type,
            "title": info.get("title", md_file.stem),
            "year": info.get("year", ""),
            "stage": info.get("stage", ""),
            "region": info.get("region", ""),
            "source_grade": info.get("source_grade", ""),
            "keywords": keywords,
            "last_modified": datetime.fromtimestamp(md_file.stat().st_mtime).isoformat(),
        }
        manifest.append(entry)

    return manifest


def build_search_index(manifest: list) -> dict:
    """构建搜索索引"""
    index = {
        "by_type": {},
        "by_year": {},
        "by_region": {},
        "by_stage": {},
        "by_keyword": {},
    }

    for entry in manifest:
        # 按类型索引
        ptype = entry["type"]
        if ptype not in index["by_type"]:
            index["by_type"][ptype] = []
        index["by_type"][ptype].append(entry["path"])

        # 按年份索引
        year = entry.get("year")
        if year:
            if year not in index["by_year"]:
                index["by_year"][year] = []
            index["by_year"][year].append(entry["path"])

        # 按区域索引
        region = entry.get("region")
        if region:
            if region not in index["by_region"]:
                index["by_region"][region] = []
            index["by_region"][region].append(entry["path"])

        # 按学段索引
        stage = entry.get("stage")
        if stage:
            if stage not in index["by_stage"]:
                index["by_stage"][stage] = []
            index["by_stage"][stage].append(entry["path"])

        # 按关键词索引
        for kw in entry.get("keywords", []):
            if kw not in index["by_keyword"]:
                index["by_keyword"][kw] = []
            if entry["path"] not in index["by_keyword"][kw]:
                index["by_keyword"][kw].append(entry["path"])

    return index


def main():
    """主函数"""
    print("=" * 50)
    print("K12 Rocket Wiki Index Builder")
    print("=" * 50)

    # 确保 build 目录存在
    BUILD_DIR.mkdir(exist_ok=True)

    # 构建清单
    print("\n[1/3] 构建页面清单...")
    manifest = build_manifest()
    print(f"      发现 {len(manifest)} 个 Wiki 页面")

    # 构建搜索索引
    print("\n[2/3] 构建搜索索引...")
    search_index = build_search_index(manifest)

    # 统计信息
    print(f"      按类型: {dict((k, len(v)) for k, v in search_index['by_type'].items())}")
    print(f"      按年份: {list(search_index['by_year'].keys())}")
    print(f"      关键词数: {len(search_index['by_keyword'])}")

    # 保存 manifest.json
    manifest_path = BUILD_DIR / "manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n[3/3] 已保存: {manifest_path}")

    # 保存 search_index.json
    index_path = BUILD_DIR / "search_index.json"
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(search_index, f, ensure_ascii=False, indent=2)
    print(f"      已保存: {index_path}")

    print("\n" + "=" * 50)
    print("索引构建完成!")
    print("=" * 50)

    return 0


if __name__ == '__main__':
    exit(main())

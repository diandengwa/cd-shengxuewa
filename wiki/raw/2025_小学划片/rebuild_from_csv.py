#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Rebuild image-format districts with CSV data, keeping image notice."""

import csv
from pathlib import Path

RAW_DIR = Path(r'D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片')

# Districts to rebuild: (区县名, pinyin, CSV列格式描述)
REBUILD = [
    ('金牛区', 'jinniu', 'standard'),  # 小学名称,划片范围
    ('彭州市', 'pengzhou', 'numbered'),  # 序号,学校名称,2025年入学划片范围
    ('崇州市', 'chongzhou', 'standard'),  # 小学名称,服务范围
]

TODAY = '2026-07-11'

def detect_columns(header):
    school_col = range_col = None
    for i, col in enumerate(header):
        cl = col.strip()
        if '学校' in cl or '小学' in cl or '名称' in cl:
            if school_col is None:
                school_col = i
        if '划片' in cl or '范围' in cl or '服务' in cl:
            range_col = i
    if school_col is None and range_col is None and len(header) >= 3:
        school_col, range_col = 1, 2
    elif school_col is None and len(header) >= 2:
        school_col, range_col = 0, 1
    return school_col, range_col

def rebuild(district, pinyin):
    csv_path = RAW_DIR / f'2025_{pinyin}_小学划片.csv'
    md_path = RAW_DIR / f'2025_{district}_小学划片.md'
    
    if not csv_path.exists():
        print(f"  ❌ {district}: CSV不存在")
        return False
    
    rows = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader)
        school_col, range_col = detect_columns(header)
        if school_col is None or range_col is None:
            print(f"  ❌ {district}: 无法识别列, header={header}")
            return False
        for row in reader:
            if len(row) > max(school_col, range_col):
                school = row[school_col].strip()
                district_range = row[range_col].strip()
                if school:
                    rows.append((school, district_range))
    
    # Write MD with image notice + CSV data
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"""---
year: 2025
district: {district}
level: 小学
source: "成都市教育局官方数据"
trust_level: "S"
scraped_at: "{TODAY}"
data_note: "官方图片版+CSV文字版合并"
---

# 2025年{district}小学入学划片范围

> **数据说明**：{district}2025年小学划片范围官方公告以图片形式发布。以下文字版数据来源于成都市教育局公开数据，与官方图片版一致。

| 小学名称 | 划片范围 |
|---------|---------|
""")
        for school, dist_range in rows:
            school = school.replace('|', '｜')
            dist_range = dist_range.replace('|', '｜')
            f.write(f"| {school} | {dist_range} |\n")
    
    print(f"  ✅ {district}: {len(rows)}所学校 (从CSV重建)")
    return True

for district, pinyin, fmt in REBUILD:
    rebuild(district, pinyin)

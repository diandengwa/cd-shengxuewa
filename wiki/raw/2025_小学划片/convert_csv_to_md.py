#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Convert raw CSV files to standardized Markdown format for 2025 小学划片 data."""

import csv
import os
from datetime import date
from pathlib import Path

PINYIN_TO_CHINESE = {
    'chenghua': '成华区',
    'chongzhou': '崇州市',
    'dayi': '大邑县',
    'dongbuxinqu': '东部新区',
    'dujiangyan': '都江堰市',
    'gaoxin': '高新区',
    'jianyang': '简阳市',
    'jinjiang': '锦江区',
    'jinniu': '金牛区',
    'jintang': '金堂县',
    'longquanyi': '龙泉驿区',
    'pengzhou': '彭州市',
    'pidu': '郫都区',
    'pujiang': '蒲江县',
    'qingbaijiang': '青白江区',
    'qingyang': '青羊区',
    'qionglai': '邛崃市',
    'shuangliu': '双流区',
    'wenjiang': '温江区',
    'wuhou': '武侯区',
    'xindu': '新都区',
    'xinjin': '新津区',
}

RAW_DIR = Path(r'D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片')
TODAY = str(date.today())

def detect_columns(header):
    """Detect which columns contain school name and district range."""
    school_col = None
    range_col = None
    for i, col in enumerate(header):
        col_lower = col.strip().lower()
        if '学校' in col_lower or '小学' in col_lower or '名称' in col_lower:
            if school_col is None:  # take first match
                school_col = i
        if '划片' in col_lower or '范围' in col_lower or '服务' in col_lower:
            range_col = i
    # Fallback: if only 2 columns and one has 序号, the other two are school and range
    if school_col is None and range_col is None and len(header) >= 3:
        # Format: 序号, 学校名称, 划片范围
        school_col = 1
        range_col = 2
    elif school_col is None and len(header) >= 2:
        school_col = 0
        range_col = 1
    return school_col, range_col

def convert_csv_to_md(csv_path, output_path, district_name):
    """Convert a single CSV file to Markdown."""
    rows = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader)
        school_col, range_col = detect_columns(header)
        if school_col is None or range_col is None:
            print(f"  WARNING: Cannot detect columns in {csv_path.name}, header={header}")
            return False
        for row in reader:
            if len(row) > max(school_col, range_col):
                school = row[school_col].strip()
                district = row[range_col].strip()
                if school:
                    rows.append((school, district))

    # Write Markdown
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"""---
year: 2025
district: {district_name}
level: 小学
source: 成都市教育局官方数据
converted_at: {TODAY}
---

# 2025年{district_name}小学入学划片范围

| 小学名称 | 划片范围 |
|---------|---------|
""")
        for school, district in rows:
            # Escape pipe characters in content
            school = school.replace('|', '｜')
            district = district.replace('|', '｜')
            f.write(f"| {school} | {district} |\n")

    print(f"  ✅ {csv_path.name} → {output_path.name} ({len(rows)} schools)")
    return True

def main():
    # Get all CSV files
    csv_files = sorted(RAW_DIR.glob('2025_*_小学划片.csv'))
    print(f"Found {len(csv_files)} CSV files to convert\n")

    converted = 0
    failed = 0
    for csv_path in csv_files:
        # Extract pinyin from filename: 2025_jinjiang_小学划片.csv → jinjiang
        parts = csv_path.stem.split('_')
        if len(parts) >= 3:
            pinyin = parts[1]
        else:
            print(f"  ❌ Cannot parse filename: {csv_path.name}")
            failed += 1
            continue

        district_name = PINYIN_TO_CHINESE.get(pinyin)
        if not district_name:
            print(f"  ❌ Unknown pinyin: {pinyin}")
            failed += 1
            continue

        # Output filename: 2025_锦江区_小学划片.md
        output_path = RAW_DIR / f"2025_{district_name}_小学划片.md"

        try:
            if convert_csv_to_md(csv_path, output_path, district_name):
                converted += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ❌ Error converting {csv_path.name}: {e}")
            failed += 1

    print(f"\n=== Conversion Complete ===")
    print(f"  Converted: {converted}")
    print(f"  Failed: {failed}")

    # Check existing MD files (天府新区, 锦江区) - these were already scraped
    existing_mds = sorted(RAW_DIR.glob('2025_*_小学划片.md'))
    print(f"  Total MD files: {len(existing_mds)}")

if __name__ == '__main__':
    main()

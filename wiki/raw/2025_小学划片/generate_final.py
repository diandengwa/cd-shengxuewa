import os
import re
import csv
import json

OUTPUT_DIR = r'd:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片'
JSON_FILE = os.path.join(OUTPUT_DIR, 'bendibao_raw_extract.json')

def html_to_lines(html):
    """Convert HTML to list of clean text lines."""
    html = re.sub(r'<br\s*/?\s*>', '\n', html)
    html = re.sub(r'</?(?:tr|p|div|h[1-6]|li|ul|ol|table|thead|tbody|tfoot)\b[^>]*>', '\n', html)
    html = re.sub(r'</?(?:td|th)\b[^>]*>', ' | ', html)
    html = re.sub(r'<[^>]+>', '', html)
    html = html.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    html = re.sub(r'[ \t]+', ' ', html)
    return [l.strip() for l in html.split('\n') if l.strip()]

SKIP_PATTERNS = ['温馨提示', '分页导航', '本地宝', '微信搜索', '上一篇', '下一篇', '余下全文', 'Copyright', '备案号', '相关推荐', '猜你喜欢', '首页', '末页', '余下全文', 'var newNode', 'document.getElementById', 'add_ewm_content', 'adInArticle', '手机访问', '成都本地宝首页', '导读']

def should_skip(line):
    return any(p in line for p in SKIP_PATTERNS) or re.match(r'^第\d+页', line)

def parse_csv_data(district_name):
    csv_map = {
        '双流区': '2025_shuangliu_小学划片.csv',
        '郫都区': '2025_pidu_小学划片.csv',
        '温江区': '2025_wenjiang_小学划片.csv',
        '龙泉驿区': '2025_longquanyi_小学划片.csv',
        '青白江区': '2025_qingbaijiang_小学划片.csv',
        '新津区': '2025_xinjin_小学划片.csv',
        '新都区': '2025_xindu_小学划片.csv',
        '东部新区': '2025_dongbuxinqu_小学划片.csv',
    }
    filename = csv_map.get(district_name)
    if not filename:
        return []
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return []
    
    schools = []
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return []
        school_col = -1
        zone_col = -1
        for i, h in enumerate(header):
            h_lower = h.strip()
            if any(kw in h_lower for kw in ['学校', 'school']):
                school_col = i
            if any(kw in h_lower for kw in ['划片', '范围', '服务', '招生']):
                zone_col = i
        if school_col == -1:
            school_col = 1 if len(header) > 2 else 0
        if zone_col == -1:
            zone_col = len(header) - 1
        
        for row in reader:
            if len(row) > max(school_col, zone_col):
                school_name = row[school_col].strip()
                zone = row[zone_col].strip()
                if school_name:
                    schools.append((school_name, zone))
    return schools

# ============================================================
# Per-district parsers for bendibao HTML data
# ============================================================

def parse_wenjiang(lines):
    """Parse 温江区: table format with school names and zones, handling split cells."""
    schools = []
    # Join continuation lines: "成都师范学院\n附属实验学校" -> "成都师范学院附属实验学校"
    # Process by looking at school-zone patterns
    
    data_start = -1
    for i, line in enumerate(lines):
        if '学校' in line and '就学服务范围' in line:
            data_start = i + 1
            break
    if data_start == -1:
        for i, line in enumerate(lines):
            if '划片范围' in line and '学校' in line:
                data_start = i + 1
                break
    if data_start == -1:
        return []
    
    # Rebuild: merge lines that are clearly continuations
    merged_lines = []
    for i in range(data_start, len(lines)):
        line = lines[i]
        if should_skip(line):
            continue
        
        # Check if this is a continuation line (starts with Chinese, no school keyword, short)
        if merged_lines and not any(kw in line for kw in ['小学', '学校', '实验', '附属', '外国语']):
            # Could be continuation of zone or a split name
            # If previous line looks like a partial name (ends without zone-like content)
            prev = merged_lines[-1]
            if prev in ['成都师范学院', '西南财大']:
                # Merge with next line to form full school name
                merged_lines[-1] = prev + line
                continue
        
        # Skip page number markers and non-data
        if re.match(r'^\d{2}$', line):
            continue
        if '（一）' in line or '（二）' in line or '(一)' in line or '(二)' in line:
            continue
        if '备注' in line or '解释权' in line or '公告' in line or '电话' in line:
            continue
        if '重要提示' in line or '学位确认' in line or '到校报到' in line:
            continue
        if '报名需带材料' in line or '户口簿' in line:
            continue
        if '1.学校相关信息' in line or '2.报名需带' in line:
            continue
        
        merged_lines.append(line)
    
    # Now parse the merged lines
    current_school = None
    current_zone = []
    
    for line in merged_lines:
        # Check if this line is a school name
        is_school = False
        if any(kw in line for kw in ['小学', '学校', '实验', '外国语']):
            # It's likely a school name if it doesn't have a very long zone description
            # or if it's the merged form (e.g. "成都师范学院附属实验学校")
            zone_chars = sum(1 for c in line if c in '，、、号路段街路村社区组')
            total_chars = len(line)
            if total_chars < 50 or (zone_chars / max(total_chars, 1) < 0.3):
                is_school = True
        
        if is_school:
            if current_school:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = line
            current_zone = []
        else:
            if current_school:
                # Zone content
                if '|' in line:
                    # Table format: extract zone from | separators
                    parts = [p.strip() for p in line.split('|') if p.strip()]
                    for p in parts:
                        if p and not any(kw in p for kw in ['小学', '学校']):
                            current_zone.append(p)
                else:
                    current_zone.append(line)
    
    if current_school:
        schools.append((current_school, '，'.join(current_zone)))
    
    return schools

def parse_qingbaijiang(lines):
    """Parse 青白江区: 'XX小学服务范围' format."""
    schools = []
    current_school = None
    current_zone = []
    
    for line in lines:
        if should_skip(line):
            continue
        
        match = re.match(r'^(.+?(?:小学|学校).+?)服务范围\s*$', line)
        if match:
            if current_school:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = match.group(1).strip()
            current_zone = []
            continue
        
        # Standalone school name
        if re.match(r'^[\u4e00-\u9fa5]+(?:小学|学校)', line) and len(line) < 40 and '服务范围' not in line and '户籍' not in line and '社区' not in line and '号' not in line:
            if current_school and current_zone:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = line
            current_zone = []
            continue
        
        # Sub-campus
        if re.match(r'^[（\(].+?(?:小学|学校).+?[）\)]$', line):
            if current_school:
                current_school = current_school + line
            continue
        
        # Skip page numbers
        if re.match(r'^\d{2}$', line):
            continue
        
        if current_school:
            if re.match(r'^[\d\-]+$', line) and len(line) > 5:
                continue
            current_zone.append(line)
    
    if current_school:
        schools.append((current_school, '，'.join(current_zone)))
    return schools

def parse_xinjin(lines):
    """Parse 新津区: '1.学校名' with ◉划片范围 and ◉咨询电话."""
    schools = []
    current_school = None
    current_zone = []
    in_zone = False
    
    for line in lines:
        if should_skip(line):
            continue
        
        match = re.match(r'^(\d+)[\.、．]\s*(.+?(?:小学|学校|实验).+)', line)
        if match:
            if current_school:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = match.group(2).strip()
            current_zone = []
            in_zone = False
            continue
        
        if '◉' in line and '划片范围' in line:
            in_zone = True
            remainder = re.sub(r'.*划片范围[：:]*\s*', '', line).strip()
            if remainder:
                current_zone.append(remainder)
            continue
        
        if '◉' in line and '咨询电话' in line:
            in_zone = False
            continue
        
        if line.startswith('划片范围') or line.startswith('划片：'):
            in_zone = True
            remainder = re.sub(r'^划片[范围：:]*\s*', '', line).strip()
            if remainder:
                current_zone.append(remainder)
            continue
        
        if in_zone and current_school:
            current_zone.append(line)
    
    if current_school:
        schools.append((current_school, '，'.join(current_zone)))
    return schools

def parse_xindu(lines):
    """Parse 新都区: school names with campus sub-entries."""
    schools = []
    current_main = None
    current_campus = None
    current_zone = []
    in_zone = False
    
    for line in lines:
        if should_skip(line):
            continue
        
        # Skip standalone campus numbers
        if re.match(r'^\d+$', line) and len(line) <= 2:
            continue
        
        # Main school name
        if any(kw in line for kw in ['小学', '学校']) and len(line) < 30 and not any(zw in line for zw in ['社区', '街道', '村', '号', '路', '楼盘', '涉及']):
            if current_main and current_zone:
                name = current_main
                if current_campus:
                    name = f"{current_main}（{current_campus}）"
                schools.append((name, '，'.join(current_zone)))
            current_main = line
            current_campus = None
            current_zone = []
            in_zone = True
            continue
        
        # Campus
        campus_match = re.match(r'^([\u4e00-\u9fa5]*校区|本部)[：:]?\s*(.*)', line)
        if campus_match:
            if current_main and current_campus and current_zone:
                name = f"{current_main}（{current_campus}）"
                schools.append((name, '，'.join(current_zone)))
            current_campus = campus_match.group(1)
            remainder = campus_match.group(2).strip()
            current_zone = []
            if remainder:
                current_zone.append(remainder)
            continue
        
        if '校区' in line and len(line) < 20:
            if current_main and current_campus and current_zone:
                name = f"{current_main}（{current_campus}）"
                schools.append((name, '，'.join(current_zone)))
            current_campus = line.strip('：:').strip()
            current_zone = []
            continue
        
        if in_zone and current_main and line:
            current_zone.append(line)
    
    if current_main and current_zone:
        name = current_main
        if current_campus:
            name = f"{current_main}（{current_campus}）"
        schools.append((name, '，'.join(current_zone)))
    
    return schools

def generate_markdown(district_name, schools):
    md = f"""---
title: "2025年{district_name}小学入学划片范围"
source: "成都本地宝/区教育局"
publish_date: "2025-06-17"
archive_date: "2026-04-30"
policy_year: 2025
policy_type: "小学划片"
city: "成都市"
district: "{district_name}"
trust_level: "B"
status: "历史参考"
---

# 2025年{district_name}小学入学划片范围

> 数据来源：成都本地宝 / {district_name}教育局
> 发布日期：2025-06-17
> 归档日期：2026-04-30

"""
    
    if not schools:
        md += "\n*暂未获取到完整数据*\n"
        return md
    
    for i, (school, zone) in enumerate(schools, 1):
        md += f"## {i}. {school}\n\n"
        if zone:
            md += f"**划片范围：** {zone}\n\n"
        else:
            md += "**划片范围：** 详见原文\n\n"
    
    md += f"\n---\n\n*共 {len(schools)} 所小学*\n"
    return md

def main():
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        bendibao_data = json.load(f)
    
    # 双流区: already generated separately with 45 schools from QQ News
    print("双流区: already generated (45 schools from QQ News)")
    
    # 郫都区: data is image-based, use CSV
    pidu_csv = parse_csv_data('郫都区')
    md = generate_markdown('郫都区', pidu_csv)
    filepath = os.path.join(OUTPUT_DIR, '2025_郫都区_小学划片.md')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"郫都区: {len(pidu_csv)} schools -> {filepath}")
    
    # 温江区: parse HTML with improved parser + merge CSV
    wenjiang_html = parse_wenjiang(html_to_lines(bendibao_data['温江区']['content']))
    wenjiang_csv = parse_csv_data('温江区')
    # Merge: use HTML as base (more detailed zones), add CSV schools not in HTML
    html_names = {s[0] for s in wenjiang_html}
    for name, zone in wenjiang_csv:
        if name not in html_names:
            wenjiang_html.append((name, zone))
            html_names.add(name)
    # Remove noise entries
    wenjiang_final = [(n, z) for n, z in wenjiang_html if n not in ('（小学部）', '1.学校相关信息') and not n.startswith('var ')]
    md = generate_markdown('温江区', wenjiang_final)
    filepath = os.path.join(OUTPUT_DIR, '2025_温江区_小学划片.md')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"温江区: {len(wenjiang_final)} schools -> {filepath}")
    
    # 龙泉驿区: data is image-based, use CSV
    longquanyi_csv = parse_csv_data('龙泉驿区')
    md = generate_markdown('龙泉驿区', longquanyi_csv)
    filepath = os.path.join(OUTPUT_DIR, '2025_龙泉驿区_小学划片.md')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"龙泉驿区: {len(longquanyi_csv)} schools -> {filepath}")
    
    # 青白江区: parse HTML + merge CSV
    qingbaijiang_html = parse_qingbaijiang(html_to_lines(bendibao_data['青白江区']['content']))
    qingbaijiang_csv = parse_csv_data('青白江区')
    html_names = {s[0] for s in qingbaijiang_html}
    for name, zone in qingbaijiang_csv:
        if name not in html_names:
            qingbaijiang_html.append((name, zone))
            html_names.add(name)
    md = generate_markdown('青白江区', qingbaijiang_html)
    filepath = os.path.join(OUTPUT_DIR, '2025_青白江区_小学划片.md')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"青白江区: {len(qingbaijiang_html)} schools -> {filepath}")
    
    # 新津区: parse HTML + merge CSV
    xinjin_html = parse_xinjin(html_to_lines(bendibao_data['新津区']['content']))
    xinjin_csv = parse_csv_data('新津区')
    html_names = {s[0] for s in xinjin_html}
    for name, zone in xinjin_csv:
        if name not in html_names:
            xinjin_html.append((name, zone))
            html_names.add(name)
    md = generate_markdown('新津区', xinjin_html)
    filepath = os.path.join(OUTPUT_DIR, '2025_新津区_小学划片.md')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"新津区: {len(xinjin_html)} schools -> {filepath}")
    
    # 新都区: parse HTML
    xindu_html = parse_xindu(html_to_lines(bendibao_data['新都区']['content']))
    xindu_csv = parse_csv_data('新都区')
    html_names = {s[0] for s in xindu_html}
    for name, zone in xindu_csv:
        if name not in html_names:
            xindu_html.append((name, zone))
            html_names.add(name)
    md = generate_markdown('新都区', xindu_html)
    filepath = os.path.join(OUTPUT_DIR, '2025_新都区_小学划片.md')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"新都区: {len(xindu_html)} schools -> {filepath}")
    
    # 东部新区: use CSV
    dongbu_csv = parse_csv_data('东部新区')
    md = generate_markdown('东部新区', dongbu_csv)
    filepath = os.path.join(OUTPUT_DIR, '2025_东部新区_小学划片.md')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"东部新区: {len(dongbu_csv)} schools -> {filepath}")
    
    print("\n=== Summary ===")
    total = 45 + len(pidu_csv) + len(wenjiang_final) + len(longquanyi_csv) + len(qingbaijiang_html) + len(xinjin_html) + len(xindu_html) + len(dongbu_csv)
    print(f"Total schools across all 8 districts: {total}")

if __name__ == '__main__':
    main()

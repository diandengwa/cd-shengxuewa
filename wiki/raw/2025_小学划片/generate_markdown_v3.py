import json
import os
import re
import csv

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

SKIP_PATTERNS = ['温馨提示', '分页导航', '本地宝', '微信搜索', '上一篇', '下一篇', '余下全文', 'Copyright', '备案号', '相关推荐', '猜你喜欢', '第1页', '第2页', '第3页', '第4页', '第5页', '第6页', '第7页', '第8页', '第9页', '第10', '第11', '第12', '第13', '第14', '第15', '第16', '第17', '第18', '第19', '第20', '第21', '第22', '第23', '首页', '末页', '附件']

def should_skip(line):
    return any(p in line for p in SKIP_PATTERNS)

def parse_wenjiang(lines):
    """Parse 温江区 format: table with | separators."""
    schools = []
    
    # Find the data section (after header row with 学校 and 就学服务范围)
    data_start = -1
    for i, line in enumerate(lines):
        if '学校' in line and '就学服务范围' in line:
            data_start = i + 1
            break
    
    if data_start == -1:
        # Try finding "划片范围" header
        for i, line in enumerate(lines):
            if '划片范围' in line:
                data_start = i + 1
                break
    
    if data_start == -1:
        return []
    
    # Parse table rows
    current_school = None
    current_zone = None
    
    # Look for section markers like "(一)非学位预警学校就学服务范围"
    in_data = True
    
    for i in range(data_start, len(lines)):
        line = lines[i]
        if should_skip(line):
            continue
        
        # Skip section headers
        if line.startswith('(一)') or line.startswith('(二)') or line.startswith('（一）') or line.startswith('（二）'):
            if '学位预警' in line or '非学位预警' in line:
                continue
        
        # Skip lines that are just notes
        if '备注' in line or '解释权' in line or '公告' in line or '电话' in line or '安全有序' in line:
            continue
        
        # Check if line contains | (table format)
        if '|' in line:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 2:
                # School name and zone in same row
                school_name = parts[0]
                zone = parts[-1]
                if school_name and any(kw in school_name for kw in ['小学', '学校', '实验', '附属', '外国语']):
                    if current_school:
                        schools.append((current_school, current_zone or ''))
                    current_school = school_name
                    current_zone = zone
                elif current_school and zone:
                    # Continuation of zone
                    current_zone += '，' + zone
            elif len(parts) == 1:
                # Might be school name without zone
                if any(kw in parts[0] for kw in ['小学', '学校', '实验', '附属', '外国语']):
                    if current_school:
                        schools.append((current_school, current_zone or ''))
                    current_school = parts[0]
                    current_zone = ''
        else:
            # Non-table line
            if any(kw in line for kw in ['小学', '学校', '实验', '附属', '外国语']) and len(line) < 60:
                # Could be a school name
                if current_school:
                    schools.append((current_school, current_zone or ''))
                current_school = line
                current_zone = ''
            elif current_school:
                # Zone continuation
                if current_zone:
                    current_zone += '，' + line
                else:
                    current_zone = line
    
    if current_school:
        schools.append((current_school, current_zone or ''))
    
    return schools

def parse_qingbaijiang(lines):
    """Parse 青白江区 format: 'XX小学服务范围' followed by zone description."""
    schools = []
    
    current_school = None
    current_zone = []
    
    for line in lines:
        if should_skip(line):
            continue
        
        # Match "XX小学服务范围" or "XX学校服务范围"
        match = re.match(r'^(.+?(?:小学|学校).+?)服务范围\s*$', line)
        if match:
            if current_school:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = match.group(1).strip()
            current_zone = []
            continue
        
        # Match standalone school name like "成都市实验小学新雅校区"
        if re.match(r'^[\u4e00-\u9fa5]+(?:小学|学校)', line) and len(line) < 40 and '服务范围' not in line and '户籍' not in line:
            # This might be a standalone school name line
            if current_school and current_zone:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = line
            current_zone = []
            continue
        
        # Match sub-campus like "(青白江区陆港第一小学校)"
        if re.match(r'^[（\(].+?(?:小学|学校).+?[）\)]$', line):
            if current_school:
                current_school = current_school + line
            continue
        
        # Skip page number markers
        if re.match(r'^\d{2}$', line):
            continue
        
        if current_school:
            # Skip phone numbers
            if re.match(r'^[\d\-]+$', line) and len(line) > 5:
                continue
            current_zone.append(line)
    
    if current_school:
        schools.append((current_school, '，'.join(current_zone)))
    
    return schools

def parse_xinjin(lines):
    """Parse 新津区 format: '1.学校名' with ◉划片范围 and ◉咨询电话."""
    schools = []
    
    current_school = None
    current_zone = []
    in_zone = False
    
    for line in lines:
        if should_skip(line):
            continue
        
        # Match numbered school entry
        match = re.match(r'^(\d+)[\.、．]\s*(.+?(?:小学|学校|实验).+)', line)
        if match:
            if current_school:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = match.group(2).strip()
            current_zone = []
            in_zone = False
            continue
        
        # Match ◉划片范围
        if '◉' in line and '划片范围' in line:
            in_zone = True
            remainder = re.sub(r'.*划片范围[：:]*\s*', '', line).strip()
            if remainder:
                current_zone.append(remainder)
            continue
        
        # Match ◉咨询电话 - end zone
        if '◉' in line and '咨询电话' in line:
            in_zone = False
            continue
        
        # Also match just "划片范围：" without ◉
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
    """Parse 新都区 format: school names with campus numbers."""
    schools = []
    
    current_main_school = None
    current_campus = None
    current_zone = []
    in_zone = False
    
    for line in lines:
        if should_skip(line):
            continue
        
        # Skip standalone campus numbers
        if re.match(r'^\d+$', line) and len(line) <= 2:
            continue
        
        # Match main school name (short, no zone-like content)
        if any(kw in line for kw in ['小学', '学校']) and len(line) < 30 and not any(zw in line for zw in ['社区', '街道', '村', '号', '路', '楼盘']):
            # Save previous school
            if current_main_school and current_zone:
                name = current_main_school
                if current_campus:
                    name = f"{current_main_school}（{current_campus}）"
                schools.append((name, '，'.join(current_zone)))
            
            current_main_school = line
            current_campus = None
            current_zone = []
            in_zone = True
            continue
        
        # Match campus identifier like "饮马河校区：" or "本部"
        campus_match = re.match(r'^([\u4e00-\u9fa5]+校区|本部)[：:]?\s*(.*)', line)
        if campus_match:
            # Save previous campus if exists
            if current_main_school and current_campus and current_zone:
                name = f"{current_main_school}（{current_campus}）"
                schools.append((name, '，'.join(current_zone)))
            
            current_campus = campus_match.group(1)
            remainder = campus_match.group(2).strip()
            current_zone = []
            if remainder:
                current_zone.append(remainder)
            continue
        
        # Match "新城校区" pattern
        if '校区' in line and len(line) < 20:
            if current_main_school and current_campus and current_zone:
                name = f"{current_main_school}（{current_campus}）"
                schools.append((name, '，'.join(current_zone)))
            current_campus = line.strip('：:').strip()
            current_zone = []
            continue
        
        if in_zone and current_main_school:
            if line:
                current_zone.append(line)
    
    # Save last school
    if current_main_school and current_zone:
        name = current_main_school
        if current_campus:
            name = f"{current_main_school}（{current_campus}）"
        schools.append((name, '，'.join(current_zone)))
    
    return schools

def parse_csv_data(district_name):
    """Parse existing CSV data."""
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
            if len(header) >= 2:
                school_col = 1 if len(header) > 2 else 0
            else:
                school_col = 0
        
        if zone_col == -1:
            zone_col = len(header) - 1
        
        for row in reader:
            if len(row) > max(school_col, zone_col):
                school_name = row[school_col].strip()
                zone = row[zone_col].strip()
                if school_name:
                    schools.append((school_name, zone))
    
    return schools

def generate_markdown(district_name, schools):
    """Generate markdown content with frontmatter."""
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

def merge_data(html_schools, csv_schools):
    """Merge HTML and CSV data, preferring more complete data."""
    if not html_schools:
        return csv_schools
    if not csv_schools:
        return html_schools
    
    # Use the source with more entries as base
    if len(csv_schools) >= len(html_schools):
        base = list(csv_schools)
        extra = html_schools
    else:
        base = list(html_schools)
        extra = csv_schools
    
    # Add any schools from extra not already in base
    base_names = set()
    for name, zone in base:
        # Normalize name for comparison
        normalized = name.replace('（', '(').replace('）', ')').replace('校区', '').strip()
        base_names.add(normalized)
    
    for name, zone in extra:
        normalized = name.replace('（', '(').replace('）', ')').replace('校区', '').strip()
        if normalized not in base_names:
            base.append((name, zone))
            base_names.add(normalized)
    
    return base

def main():
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        bendibao_data = json.load(f)
    
    results = {}
    
    parsers = {
        '温江区': parse_wenjiang,
        '青白江区': parse_qingbaijiang,
        '新津区': parse_xinjin,
        '新都区': parse_xindu,
    }
    
    districts = ['双流区', '郫都区', '温江区', '龙泉驿区', '青白江区', '新津区', '新都区', '东部新区']
    
    for district in districts:
        print(f"\nProcessing: {district}")
        
        html_schools = []
        csv_schools = parse_csv_data(district)
        
        if district in parsers and district in bendibao_data and bendibao_data[district]['content']:
            lines = html_to_lines(bendibao_data[district]['content'])
            html_schools = parsers[district](lines)
            print(f"  HTML parsed: {len(html_schools)} schools")
        
        print(f"  CSV data: {len(csv_schools)} schools")
        
        # Merge
        final_schools = merge_data(html_schools, csv_schools)
        print(f"  After merge: {len(final_schools)} schools")
        
        md_content = generate_markdown(district, final_schools)
        
        filename = f"2025_{district}_小学划片.md"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        print(f"  Saved: {filename}")
        results[district] = len(final_schools)
    
    print(f"\n{'='*60}")
    print("Summary:")
    total = 0
    for district, count in results.items():
        print(f"  {district}: {count} schools")
        total += count
    print(f"  TOTAL: {total} schools")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()

import json
import os
import re
import csv

OUTPUT_DIR = r'd:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片'
JSON_FILE = os.path.join(OUTPUT_DIR, 'bendibao_raw_extract.json')

def html_to_text(html):
    """Convert HTML to clean text."""
    # Replace <br>, <tr>, <p>, <div> with newlines
    html = re.sub(r'<br\s*/?\s*>', '\n', html)
    html = re.sub(r'</?(?:tr|p|div|h[1-6]|li|ul|ol|table|thead|tbody|tfoot)\b[^>]*>', '\n', html)
    html = re.sub(r'</?(?:td|th)\b[^>]*>', ' | ', html)
    # Remove all other tags
    html = re.sub(r'<[^>]+>', '', html)
    # Decode HTML entities
    html = html.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    # Clean up whitespace
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n\s*\n', '\n', html)
    return html.strip()

def parse_wenjiang(text):
    """Parse 温江区 format: school name on its own line, zone description follows."""
    schools = []
    lines = text.split('\n')
    
    # Find the data section
    data_started = False
    current_school = None
    current_zone = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if '划片范围' in line and '学校' in line:
            data_started = True
            continue
        
        if not data_started:
            continue
        
        # Skip non-data lines
        if any(skip in line for skip in ['温馨提示', '分页导航', '本地宝', '微信搜索', '上一篇', '下一篇', '余下全文', 'Copyright', '备案号', '相关推荐']):
            continue
        
        # Check if this is a school name (no colon/descriptor, and contains school keywords)
        is_school = False
        if any(kw in line for kw in ['小学', '学校', '实验', '附属', '外国语']):
            # It's likely a school name if it doesn't have a long zone description
            # School names are typically short
            if len(line) < 50 and not any(sep in line for sep in ['社区', '街道', '村', '号']):
                is_school = True
        
        if is_school:
            if current_school:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = line
            current_zone = []
        else:
            if current_school:
                current_zone.append(line)
    
    if current_school:
        schools.append((current_school, '，'.join(current_zone)))
    
    return schools

def parse_qingbaijiang(text):
    """Parse 青白江区 format: numbered school entries with service ranges."""
    schools = []
    lines = text.split('\n')
    
    current_school = None
    current_zone = []
    in_school = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if any(skip in line for skip in ['温馨提示', '分页导航', '本地宝', '微信搜索', '上一篇', '下一篇', '余下全文', 'Copyright', '备案号', '相关推荐']):
            continue
        
        # Look for numbered school entries like "01 外国语小学服务范围"
        match = re.match(r'^(\d+)\s+(.+?(?:小学|学校).+?)服务范围', line)
        if match:
            if current_school:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = match.group(2).replace('服务范围', '').strip()
            current_zone = []
            in_school = True
            continue
        
        # Also match "XX小学服务范围" without number
        match = re.match(r'^(.+?(?:小学|学校).+?)服务范围', line)
        if match:
            if current_school:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = match.group(1).replace('服务范围', '').strip()
            current_zone = []
            in_school = True
            continue
        
        if in_school and current_school:
            # Skip phone numbers
            if re.match(r'^[\d\-]+$', line):
                continue
            current_zone.append(line)
    
    if current_school:
        schools.append((current_school, '，'.join(current_zone)))
    
    return schools

def parse_xinjin(text):
    """Parse 新津区 format: numbered entries with ◉划片范围 markers."""
    schools = []
    lines = text.split('\n')
    
    current_school = None
    current_zone = []
    in_zone = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if any(skip in line for skip in ['温馨提示', '分页导航', '本地宝', '微信搜索', '上一篇', '下一篇', '余下全文', 'Copyright', '备案号', '相关推荐']):
            continue
        
        # Match numbered school entry: "1.成都市新津区外国语实验学校(小学部)"
        match = re.match(r'^(\d+)[\.、．]\s*(.+?(?:小学|学校|实验).+)', line)
        if match:
            if current_school:
                schools.append((current_school, '，'.join(current_zone)))
            current_school = match.group(2).strip()
            current_zone = []
            in_zone = False
            continue
        
        # Match ◉划片范围 marker
        if '◉' in line and '划片范围' in line:
            in_zone = True
            # If there's zone text after the marker
            remainder = line.split('划片范围', 1)[-1].strip().lstrip('：:').strip()
            if remainder:
                current_zone.append(remainder)
            continue
        
        # Match ◉咨询电话 - end of zone
        if '咨询电话' in line:
            in_zone = False
            continue
        
        if in_zone and current_school:
            current_zone.append(line)
    
    if current_school:
        schools.append((current_school, '，'.join(current_zone)))
    
    return schools

def parse_xindu(text):
    """Parse 新都区 format: school names with sub-campus entries."""
    schools = []
    lines = text.split('\n')
    
    current_school = None
    current_campus = None
    current_zone = []
    in_zone = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if any(skip in line for skip in ['温馨提示', '分页导航', '本地宝', '微信搜索', '上一篇', '下一篇', '余下全文', 'Copyright', '备案号', '相关推荐']):
            continue
        
        # Skip standalone numbers (campus numbers like "1", "2")
        if re.match(r'^\d+$', line):
            if line in ['1', '2', '3']:
                current_campus = line
            continue
        
        # Match school name (typically short, contains 小学/学校)
        if any(kw in line for kw in ['小学', '学校']) and len(line) < 40 and not any(sep in line for sep in ['社区', '街道', '村', '号', '路']):
            # This could be a new school
            if current_school and current_zone:
                school_name = current_school
                if current_campus:
                    school_name = f"{current_school}（{current_campus}）"
                schools.append((school_name, '，'.join(current_zone)))
            current_school = line
            current_campus = None
            current_zone = []
            in_zone = True
            continue
        
        # Match campus name like "饮马河校区：" or "本部"
        campus_match = re.match(r'^([\u4e00-\u9fa5]+校区|本部)[：:]?\s*(.*)', line)
        if campus_match:
            current_campus = campus_match.group(1)
            remainder = campus_match.group(2).strip()
            if remainder:
                current_zone.append(remainder)
            continue
        
        if in_zone and current_school:
            # Skip phone numbers
            if re.match(r'^[\d\-]+$', line):
                continue
            current_zone.append(line)
    
    if current_school and current_zone:
        school_name = current_school
        if current_campus:
            school_name = f"{current_school}（{current_campus}）"
        schools.append((school_name, '，'.join(current_zone)))
    
    return schools

def parse_csv_data(district_name):
    """Parse existing CSV data for a district."""
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

def generate_markdown(district_name, schools, data_source='bendibao'):
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
        md += f"**划片范围：** {zone}\n\n"
    
    md += f"\n---\n\n*共 {len(schools)} 所小学*\n"
    
    return md

def main():
    # Load bendibao data
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        bendibao_data = json.load(f)
    
    results = {}
    
    # District-specific parsers
    parsers = {
        '温江区': parse_wenjiang,
        '青白江区': parse_qingbaijiang,
        '新津区': parse_xinjin,
        '新都区': parse_xindu,
    }
    
    # Image-only districts (data in images, use CSV)
    image_districts = {'双流区', '郫都区'}
    
    districts = ['双流区', '郫都区', '温江区', '龙泉驿区', '青白江区', '新津区', '新都区', '东部新区']
    
    for district in districts:
        print(f"\nProcessing: {district}")
        
        schools = []
        source = 'csv'
        
        if district in image_districts:
            # Data is in images, use CSV
            schools = parse_csv_data(district)
            source = 'csv'
            print(f"  Image-based district, using CSV: {len(schools)} schools")
        elif district in parsers and district in bendibao_data and bendibao_data[district]['content']:
            # Use district-specific parser
            text = html_to_text(bendibao_data[district]['content'])
            schools = parsers[district](text)
            source = 'bendibao'
            print(f"  Parsed from HTML: {len(schools)} schools")
            
            # Cross-check with CSV
            csv_schools = parse_csv_data(district)
            if len(csv_schools) > len(schools):
                print(f"  CSV has more data ({len(csv_schools)} vs {len(schools)}), merging...")
                # Merge: add CSV schools not already in HTML results
                html_school_names = {s[0] for s in schools}
                for s_name, s_zone in csv_schools:
                    if s_name not in html_school_names:
                        schools.append((s_name, s_zone))
                        html_school_names.add(s_name)
                print(f"  After merge: {len(schools)} schools")
        elif district in bendibao_data and bendibao_data[district]['content']:
            # Generic HTML parsing (for districts without specific parsers)
            text = html_to_text(bendibao_data[district]['content'])
            # Use CSV as primary
            schools = parse_csv_data(district)
            source = 'csv'
            print(f"  Using CSV: {len(schools)} schools")
        else:
            # No HTML data, use CSV
            schools = parse_csv_data(district)
            source = 'csv'
            print(f"  No HTML data, using CSV: {len(schools)} schools")
        
        # Generate markdown
        md_content = generate_markdown(district, schools, source)
        
        filename = f"2025_{district}_小学划片.md"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        print(f"  Saved: {filename} ({len(schools)} schools)")
        results[district] = len(schools)
    
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

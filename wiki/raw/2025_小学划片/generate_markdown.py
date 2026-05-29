import json
import os
import re
import csv
from html.parser import HTMLParser

OUTPUT_DIR = r'd:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片'
JSON_FILE = os.path.join(OUTPUT_DIR, 'bendibao_raw_extract.json')

class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self.skip = False
        self.skip_tags = {'script', 'style', 'noscript'}
    
    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skip = True
        if tag in ('br', 'tr', 'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.result.append('\n')
        if tag in ('td', 'th'):
            self.result.append(' | ')
    
    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip = False
        if tag == 'tr':
            self.result.append('\n')
    
    def handle_data(self, data):
        if not self.skip:
            self.result.append(data)
    
    def get_text(self):
        return ''.join(self.result)

def html_to_text(html):
    extractor = HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()

def parse_bendibao_content(html_content):
    """Parse the HTML content from bendibao and extract school-zone pairs."""
    text = html_to_text(html_content)
    
    schools = []
    # Try to find patterns like:
    # 1. "学校名：划片范围" or "学校名:划片范围"
    # 2. Table format with | separators
    # 3. Numbered list format
    
    lines = text.split('\n')
    current_school = None
    current_zone = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Skip non-content lines
        if any(skip in line for skip in ['上一篇', '下一篇', '相关推荐', '分享到', '本地宝', '猜你喜欢', 'Copyright', '备案号']):
            continue
        
        # Pattern: school name followed by colon/dash and zone description
        # Try various separators
        for sep in ['：', ':', '—', '–']:
            if sep in line:
                parts = line.split(sep, 1)
                if len(parts) == 2:
                    school_part = parts[0].strip()
                    zone_part = parts[1].strip()
                    
                    # Check if the school part looks like a school name
                    if any(kw in school_part for kw in ['小学', '学校', '实验', '附属', '外国语']):
                        if current_school:
                            schools.append((current_school, current_zone))
                        current_school = school_part
                        # Clean up numbering
                        current_school = re.sub(r'^[\d]+[\.、）)]\s*', '', current_school)
                        current_zone = zone_part
                        break
        else:
            # If no separator found, might be continuation of zone or new content
            if current_school and current_zone:
                current_zone += '，' + line
            elif any(kw in line for kw in ['小学', '学校', '实验', '附属', '外国语']):
                if current_school:
                    schools.append((current_school, current_zone))
                current_school = re.sub(r'^[\d]+[\.、）)]\s*', '', line)
                current_zone = ''
    
    if current_school:
        schools.append((current_school, current_zone))
    
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
        
        # Determine column indices
        school_col = -1
        zone_col = -1
        
        for i, h in enumerate(header):
            h_lower = h.strip().lower()
            if any(kw in h_lower for kw in ['学校', 'school']):
                school_col = i
            if any(kw in h_lower for kw in ['划片', '范围', 'zone', '服务', '招生']):
                zone_col = i
        
        if school_col == -1:
            # Try second column as school name
            if len(header) >= 2:
                school_col = 1 if len(header) > 2 else 0
            else:
                school_col = 0
        
        if zone_col == -1:
            # Last column is usually the zone
            zone_col = len(header) - 1
        
        for row in reader:
            if len(row) > max(school_col, zone_col):
                school_name = row[school_col].strip()
                zone = row[zone_col].strip()
                if school_name and any(kw in school_name for kw in ['小学', '学校', '实验', '附属', '外国语']):
                    schools.append((school_name, zone))
    
    return schools

def generate_markdown(district_name, schools, source_url=''):
    """Generate markdown content with frontmatter."""
    frontmatter = f"""---
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
        frontmatter += "\n*暂未获取到完整数据*\n"
        return frontmatter
    
    # Group by area/town if applicable (some districts have town prefixes)
    # For now, just list all schools
    for i, (school, zone) in enumerate(schools, 1):
        frontmatter += f"## {i}. {school}\n\n"
        frontmatter += f"**划片范围：** {zone}\n\n"
    
    frontmatter += f"\n---\n\n*共 {len(schools)} 所小学*\n"
    
    return frontmatter

def main():
    # Load bendibao data
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        bendibao_data = json.load(f)
    
    districts = ['双流区', '郫都区', '温江区', '龙泉驿区', '青白江区', '新津区', '新都区', '东部新区']
    
    results = {}
    
    for district in districts:
        print(f"\nProcessing: {district}")
        
        # Try bendibao HTML data first
        schools_from_html = []
        if district in bendibao_data and bendibao_data[district]['content']:
            html_content = bendibao_data[district]['content']
            text = html_to_text(html_content)
            
            # Better parsing: extract structured data from the HTML
            # Look for table rows or list items
            schools_from_html = parse_bendibao_content(html_content)
            print(f"  From HTML: {len(schools_from_html)} schools")
        
        # Get CSV data
        schools_from_csv = parse_csv_data(district)
        print(f"  From CSV: {len(schools_from_csv)} schools")
        
        # Use the source with more data
        if len(schools_from_html) >= len(schools_from_csv) and schools_from_html:
            schools = schools_from_html
            source = 'bendibao'
        else:
            schools = schools_from_csv
            source = 'csv'
        
        print(f"  Using: {source} ({len(schools)} schools)")
        
        # Generate markdown
        md_content = generate_markdown(district, schools)
        
        # Save
        filename = f"2025_{district}_小学划片.md"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        print(f"  Saved: {filepath}")
        results[district] = len(schools)
    
    print(f"\n{'='*60}")
    print("Summary:")
    for district, count in results.items():
        print(f"  {district}: {count} schools")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()

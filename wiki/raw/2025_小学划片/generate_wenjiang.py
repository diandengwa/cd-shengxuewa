import os
import csv

OUTPUT_DIR = r'd:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片'

def parse_csv_data(district_name):
    csv_map = {
        '温江区': '2025_wenjiang_小学划片.csv',
        '郫都区': '2025_pidu_小学划片.csv',
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
        
        # Determine columns
        school_col = 0
        zone_col = 1
        for i, h in enumerate(header):
            h_lower = h.strip()
            if any(kw in h_lower for kw in ['学校', 'school']):
                school_col = i
            if any(kw in h_lower for kw in ['划片', '范围', '服务', '就学']):
                zone_col = i
        
        for row in reader:
            if len(row) > max(school_col, zone_col):
                school_name = row[school_col].strip()
                zone = row[zone_col].strip()
                if school_name:
                    schools.append((school_name, zone))
    return schools

# Also add data from the HTML that's not in CSV
# The CSV for 温江区 has 14 schools, but the HTML has more detailed data
# Let's manually add the schools that were in HTML but missing from CSV

wenjiang_extra_from_html = [
    ("东大街一小", "万春东路、万春路、迎晖路（新东路）、景阳巷、蒜市街、文化路、白马庙街、战备渠（北路南路）、柳北一街、柳北二街、北巷子、柳城鱼凫社区、春凫街、东大街151号、泰康路、泰康东路、鱼凫路、柳城北街（999号除外）、双春巷、柳城新村一巷"),
    ("东大街二小", "东大街（151号除外）、隆建街、南巷子、文庙街、文武路、行署路、团结巷、赞元街、小南街、和宁街、香榭里街、社学巷、长安路（门牌号为单号）、东巷子、太平街（门牌号为单号）、临江路、临江路北段、临江路南段、滨江路北段（1000号除外）、滨江路南段、合江村、合江路、柳城大道东段、两河路东段、南熏大道一段88号、温泉路、大南街、商业街、商业新街（61号除外）、西大街、云溪路（500号、515号、518号除外）、来凤路、航天路、金强步行街"),
    ("东大街二小长安路分校", "长安路（门牌号为双号）、太平街（门牌号为双号）、建设路、南熏大道一段（84号、188号、366号）、龙湾路"),
    ("庆丰街小学", "河坝街、金乌街、金乌横街、育才巷、龙潭巷、麻市街、庆丰街、西凤街、黄金路、永康路、游家巷、凤溪大道北段、云凤路、彭家巷、王家二巷、中学巷、柳春路、新南路、金河东路、新建路、云凤横街、德通桥路、德通桥南路、南林路、金河西路、德通桥1-4组、和平路、柳平一街、柳平二街"),
    ("温江区实验学校（中医大附小）", "柳城永宁路、两河路西段、柳城大道西段、南熏大道二段（139号、582号、630号、988号）、南熏大道三段（366号、855号、878号）、南熏大道四段、杨柳西路北段、杨柳西路中段、杨柳东路中段、凤溪大道中段、柳浪湾北一街、柳浪湾北二街、南浦路西段（东段）、柳河路、柳城柳河南路、永宁正街、大河街、小河街、柳南一路至七路、双南街、柳林路（99号、158号）、文府苑路、双河一至三巷、五一路、柳台大道东段、柳浪湾街、柳浪湾南一街、柳浪湾北一巷-北五巷、万盛路、双柳一巷至三巷、和平社区（2-7组）、柳凤巷、红泰路、云溪路515号、云溪路518号"),
    ("光华实验小学", "公平花都大道西段266号、花季街、同兴东路、燎原路、天宝西街、天宝中街、锦泉街、同兴西路、光华大道三段（1818号、1868号、1998号）、诚心路、花都大道西段（399号、555号、588号、622号、777号、888号）、温泉大道一段（88号、336号、558号）、南熏大道一段（129号、189号、509号）"),
    ("政通小学", "凤溪大道南段（333号、555号、977号）、永和路、政通西路、政通东路、德通桥5组、新华社区、人和路、五洞桥路639号、燎原社区、光华大道三段（1333号、1969号）、政和街、南江路（199号、208号、289号、466号）、祥和街、广柳路"),
    ("鹏程小学", "涌泉大田社区、涌泉凤凰社区、涌泉共耕社区、涌泉洪江村、涌泉花土社区、涌泉前锋社区、涌泉双堰社区、官河社区、花土路（69号、1519号）、林泉南街、明光社区、康泉社区、鹏程路、七星街、清泉南街、凤凰南大街、公平温泉大道二段177号、涌泉南街、江浦路2666号、光华大道三段399号"),
    ("花都小学", "温泉大道一段1399号、江浦路（288号、888号）、清泉北街、江安路（除666号、739号外）、江浦路77号、华新路39号、林泉北街、滨河大道、乐善路、涌泉北街、温泉大道一段155号、花都大道东段、花环路、花廊路、鸣远路333号"),
    ("江安路学校", "凤凰北大街、光华大道三段（118号、336号）、江平路1111号、江安路（666号、739号）、鸡鸣路、永惠路、都堂路、竹桥二街"),
    ("东一杨柳河分校", "南江路（666号、1189号、1190号）、永兴路（633号、666号、669号、919号、1088号、1688号）、五洞桥路（850号、966号）、柳林路266号、百信路（28号、169号、188号）、杨柳西路南段、杨柳东路南段（669号除外）、南熏大道二段959号、南熏大道三段69号、凉水社区、笼堰社区、科盛路东段、柳林堰三路、柳林堰四路、柳林东路99号、柳林堰一路"),
    ("光华实小共和路分校", "花土路336号、五福路（69号、339号）、共和路（169号、333号、638号、800号）、花明路、凤溪大道南段1447号、洪江路（90号、588号、666号）、凤凰街51号、安和苑、花土E区"),
    ("川师附校", "凤溪大道南段818号、柳林堰七路、凉水路、柳林南路（269号、319号、488号）、杨柳东路南段669号"),
    ("东二农科城分校", "天乡路二段299号、春江南路（8号、98号、152号、168号）、江宁南路88号、长石小区、高辅路、团结渠东二路、团结渠东三路、科锦路、科锦南三路、科锦南二路、惠民路299号"),
    ("东一北校区", "万春镇黄石社区（距离东一北校区较近的组）、红旗村（距离东一北校区较近的组）、天乡路二段（968号、939号、888号、855号、878号、2号）、万春镇花容路、万春镇生态大道踏水段299号、金兰楠苑楼盘、万春镇南岳社区成温邛高速北一侧、和盛镇友庆（和盛金盘路距离东一北校区较近的组）"),
]

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

# Generate 温江区
csv_schools = parse_csv_data('温江区')
# Merge with HTML extra data
existing_names = {s[0] for s in csv_schools}
for name, zone in wenjiang_extra_from_html:
    if name not in existing_names:
        csv_schools.append((name, zone))
        existing_names.add(name)

# Deduplicate by removing entries where zone is empty or too short
final_schools = [(n, z) for n, z in csv_schools if z and len(z) > 5]

md = generate_markdown('温江区', final_schools)
filepath = os.path.join(OUTPUT_DIR, '2025_温江区_小学划片.md')
with open(filepath, 'w', encoding='utf-8') as f:
    f.write(md)
print(f"温江区: {len(final_schools)} schools -> {filepath}")

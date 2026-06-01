#!/usr/bin/env python3
"""
调整 OPC 竞争对手账号分类
- 创建新分类：名校（学校官方账号）
- 将15个学校账号从"自媒体号"移到"名校"
- 优先级设为 high
"""

import json
import re

# 读取现有账号数据
with open(r'D:\opc\competitors\accounts.json', 'r', encoding='utf-8') as f:
    accounts = json.load(f)

# 定义学校官方账号名称（用于识别）
school_keywords = [
    '中学', '小学', '学校', '校区', '书院', '附中', '附小',
    '嘉祥', '石室', '树德', '七中', '成都实验', '天府七中'
]

# 需要移到"名校"分类的账号（手动确认清单）
target_schools = [
    "成都石室中学",
    "成华嘉祥",
    "成都市实验小学",
    "嘉祥锦江中学",
    "四川嘉祥教育",
    "树德中学光华校区",
    "成都树德中学外国语校区",
    "成都树德中学",
    "成都七中万达学校",
    "天府七中",
    "成都市七中育才学校",
    "成都七中初中学校",
    "四川省成都市第七中学",
    "成都市第七中学",
    "成都石室天府中学 四中天府"
]

# 统计信息
moved = []
skipped = []

# 更新分类
for account in accounts:
    if account['name'] in target_schools:
        old_category = account['category']
        account['category'] = '名校'
        account['priority'] = 'high'
        moved.append({
            'name': account['name'],
            'old_category': old_category,
            'new_category': '名校'
        })

# 写入更新后的数据
with open(r'D:\opc\competitors\accounts.json', 'w', encoding='utf-8') as f:
    json.dump(accounts, f, ensure_ascii=False, indent=2)

# 输出结果
print(f"✅ 成功移动 {len(moved)} 个学校账号到'名校'分类\n")
print("移动的账号：")
for item in moved:
    print(f"  - {item['name']} ({item['old_category']} → {item['new_category']})")

# 验证新分类统计
category_stats = {}
for account in accounts:
    cat = account['category']
    if cat not in category_stats:
        category_stats[cat] = {'count': 0, 'high': 0, 'medium': 0}
    category_stats[cat]['count'] += 1
    if account['priority'] == 'high':
        category_stats[cat]['high'] += 1
    else:
        category_stats[cat]['medium'] += 1

print("\n📊 更新后的分类统计：")
for cat, stats in category_stats.items():
    print(f"  {cat}: {stats['count']} 个 (high: {stats['high']}, medium: {stats['medium']})")

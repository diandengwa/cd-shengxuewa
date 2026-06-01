import json, re, os

# === 1. Load both files ===
with open(r'D:\opc\公众号.json', 'r', encoding='utf-8') as f:
    wechat_data = json.load(f)
all_wechat = {a['fakeid']: a for a in wechat_data.get('accounts', [])}

with open(r'D:\opc\competitors\accounts.json', 'r', encoding='utf-8') as f:
    existing = json.load(f)
existing_by_fakeid = {a['fakeid']: a for a in existing}

# === 2. Classification rules ===
def classify(nickname):
    n = nickname.strip()
    # Exclude own account
    if 'K12' in n or '成都K12' in n:
        return None, None
    # 名校
    if re.search(r'(中学|高中|初中|小学|嘉祥|石室|七中|树德|四中|天府七中|育才|万达|成华嘉祥|石室天府)', n):
        return '名校', 'high'
    # 官方政策
    if re.search(r'(教育发布|考试院|教育厅|教卫|教育考试|招生|蓉e招|ZK789|阳光高考|教育局|教体局)', n):
        return '官方政策', 'high'
    # 竞品KOL - high priority (major influencers)
    high_kol = re.search(r'(壹牛|兰西|宁静姐姐|溜爸|成都商报|升学宝|升学资源圈|家长圈|本地宝成都升学|成都儿童团)', n)
    if high_kol:
        return '竞品KOL', 'high'
    # 竞品KOL - medium
    if re.search(r'(升学|家长|教育|本地宝|商报|虫爸|祺爸|春蕾|智学|蓉小|青藤|小觅|蓉城|百科)', n):
        return '竞品KOL', 'medium'
    # default
    return '竞品KOL', 'low'

# === 3. Build merged list ===
merged = []
seen_fakeids = set()

# First: keep all existing entries (preserve their note/synced_articles)
for a in existing:
    fakeid = a['fakeid']
    seen_fakeids.add(fakeid)
    # Re-classify to ensure category is correct
    cat, pri = classify(a['name'])
    if cat is None:
        continue  # skip own account
    merged.append({
        'name': a['name'],
        'fakeid': fakeid,
        'category': cat,
        'priority': pri,
        'verify_status': a.get('verify_status', 1),
        'note': a.get('note', ''),
        'synced_articles': a.get('synced_articles', 0)
    })

# Second: add new accounts from 公众号.json
for fakeid, a in all_wechat.items():
    if fakeid in seen_fakeids:
        continue
    nick = a.get('nickname', '')
    cat, pri = classify(nick)
    if cat is None:
        continue  # skip own account
    merged.append({
        'name': nick,
        'fakeid': fakeid,
        'category': cat,
        'priority': pri,
        'verify_status': 1,
        'note': f"from 公众号.json, articles={a.get('articles', 0)}",
        'synced_articles': a.get('articles', 0)
    })
    seen_fakeids.add(fakeid)

# === 4. Write accounts.json ===
os.makedirs(os.path.dirname(r'D:\opc\competitors\accounts.json'), exist_ok=True)
with open(r'D:\opc\competitors\accounts.json', 'w', encoding='utf-8') as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)

print(f"=== accounts.json updated ===")
print(f"Total accounts: {len(merged)}")
print()

from collections import Counter
cats = Counter(a['category'] for a in merged)
for c, n in cats.most_common():
    print(f"  {c}: {n}")
print()
pris = Counter(a['priority'] for a in merged)
for p, n in pris.most_common():
    print(f"  {p}: {n}")

# === 5. Create publish-config.json ===
publish_config = {
    "version": "1.0",
    "personas": [
        {
            "name": "点灯蛙",
            "target_account": "成都K12教育",
            "fakeid": "MzAxMDIzMzU2OA==",
            "description": "K12升学政策解读，面向家长",
            "publish_method": "manual_review",
            "auto_publish": False
        },
        {
            "name": "搞钱蛙",
            "target_account": "",
            "fakeid": "",
            "description": "副业/AI变现内容",
            "publish_method": "manual_review",
            "auto_publish": False
        },
        {
            "name": "养虾蛙",
            "target_account": "",
            "fakeid": "",
            "description": "水产养殖技术内容",
            "publish_method": "manual_review",
            "auto_publish": False
        },
        {
            "name": "情报蛙",
            "target_account": "",
            "fakeid": "",
            "description": "行业情报/趋势分析",
            "publish_method": "manual_review",
            "auto_publish": False
        }
    ],
    "notes": "target_account 为空时，内容生成后需手动配置发布目标"
}

with open(r'D:\opc\publish-config.json', 'w', encoding='utf-8') as f:
    json.dump(publish_config, f, ensure_ascii=False, indent=2)

print()
print("=== publish-config.json created ===")
print(f"点灯蛙 -> 成都K12教育 (fakeid: MzAxMDIzMzU2OA==)")
print("其他3个IP形象待配置 target_account")

#!/usr/bin/env python
import urllib.request
import urllib.parse
import json

API_BASE = "https://down.mptext.top/api/public/v1"
AUTH_KEY = "fb0dd96bc791414da86ade714bfc28fb"

headers = {
    "X-Auth-Key": AUTH_KEY,
    "User-Agent": "Mozilla/5.0"
}

def api_get(path):
    url = API_BASE + path
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

keywords = [
    "教育部", "四川教育", "四川省教育厅",
    "成都教育", "成都市教育局", "成都发布",
    "武侯教育", "锦江教育", "青羊教育",
    "金牛教育", "成华教育", "高新教育", "天府教育",
    "成都七中", "成都四中", "石室中学", "树德中学",
    "成都外国语", "成都实验外国语", "嘉祥", "西川中学", "师大附中",
    "小升初", "幼升小", "中考", "高考",
    "升学", "学区",
]

all_accounts = []
seen_fakeids = set()

for kw in keywords:
    try:
        encoded = urllib.parse.quote(kw)
        data = api_get(f"/account?keyword={encoded}")
        if data.get("base_resp", {}).get("ret") == 0:
            for acct in data.get("list", []):
                fid = acct.get("fakeid", "")
                if fid and fid not in seen_fakeids:
                    seen_fakeids.add(fid)
                    all_accounts.append({
                        "name": acct.get("nickname", ""),
                        "fakeid": fid,
                        "alias": acct.get("alias", ""),
                        "signature": acct.get("signature", "")[:60],
                        "verify_status": acct.get("verify_status", 0),
                        "keyword": kw,
                    })
        print(f"  ✓ [{kw}]: {len(data.get('list', []))} 个")
    except Exception as e:
        print(f"  ✗ [{kw}]: {e}")

# 去重（按 name）
seen_names = set()
unique = []
for a in all_accounts:
    if a["name"] not in seen_names:
        seen_names.add(a["name"])
        unique.append(a)

print(f"\n===== 找到 {len(unique)} 个不重复账号 =====\n")
for i, a in enumerate(unique, 1):
    v = {0:"未认证",1:"个人",2:"企业✓",3:"政府/媒体✓✓"}.get(a["verify_status"], "?")
    print(f"  {i}. {a['name']} | {v}")
    print(f"     fakeid: {a['fakeid']}")

# 保存
output = []
for a in unique:
    cat = "官方政策" if a["verify_status"] >= 2 else ("名校" if any(x in a["name"] for x in ["中","学","外国语","嘉祥","西川"]) else "竞品/KOL")
    output.append({
        "name": a["name"],
        "fakeid": a["fakeid"],
        "alias": a["alias"],
        "category": cat,
        "priority": "high" if a["verify_status"] >= 2 else "medium",
        "verify_status": a["verify_status"],
    })

out_path = "D:/opc/competitors/mptext_accounts.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n已保存到：{out_path}")
print(f"共 {len(output)} 个账号")

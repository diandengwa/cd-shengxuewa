#!/usr/bin/env python3
"""OPC 知识采矿 Agent v3 - 2026-05-31
v3 改进：
- 给每张知识卡片打时效标签（freshness: fresh/warning/stale）
- pain-points 时效30天，fact-claims 时效180天，gap-analysis 时效7天
- stale 卡片在 generate 阶段被降权或过滤
"""

import os, json
from datetime import datetime, timedelta
from pathlib import Path

# 动态日期
DATE = datetime.now().strftime("%Y-%m-%d")
KB = "D:/opc/knowledge-base"

FRESHNESS_RULES = {
    "pain-points": 30,
    "fact-claims": 180,
    "decision-frameworks": 90,
    "gap-analysis": 7,
}

def calc_freshness(card_date_str: str, card_type: str) -> tuple:
    """返回 (freshness, expire_days)"""
    try:
        dt = datetime.strptime(card_date_str[:10], "%Y-%m-%d")
    except Exception:
        dt = datetime.now()
    days = (datetime.now() - dt).days
    rule = FRESHNESS_RULES.get(card_type, 90)
    if days <= rule * 0.5:
        return ("fresh", rule - days)
    elif days <= rule:
        return ("warning", rule - days)
    else:
        return ("stale", -days)


# ===== 模拟采矿结果（实际由 DeepSeek 生成）=====
# 以下用占位数据，实际运行时由 DeepSeek API 填充

fact_claims = [
    {
        "claim": "2026年成都小升初民办摇号报名时间：6月10-12日",
        "source": "成都教育发布 2026-05-28",
        "date": "2026-05-28",
        "confidence": "high",
        "freshness": "fresh",
        "expire_days": 10,
    },
]

decision_frameworks = [
    {
        "framework": "成都小升初择校决策树：户籍优先 → 片区对口 → 民办摇号 → 补录",
        "applicable_scene": "小升初报名前",
        "date": "2026-05-28",
        "freshness": "fresh",
        "expire_days": 30,
    },
]

pain_points = [
    {
        "point": "高新区家长不知道区内区外指标名额差28个，导致择校失误",
        "level": "L2",
        "evidence": "成都教育发布 2026-05-25",
        "date": "2026-05-25",
        "freshness": "fresh",
        "expire_days": 28,
    },
]

gap_analysis = [
    {
        "gap": "2025年vs2026年：民办摇号中签率下降5%，家长焦虑指数上升",
        "trend": "negative",
        "date": "2026-05-28",
        "freshness": "fresh",
        "expire_days": 4,
    },
]


def main():
    # 给每张卡片计算时效
    global fact_claims, decision_frameworks, pain_points, gap_analysis
    
    fact_claims = [
        {**c, **dict(zip(['freshness','expire_days'], calc_freshness(c.get('date',''), 'fact-claims')))}
        for c in fact_claims
    ]
    decision_frameworks = [
        {**c, **dict(zip(['freshness','expire_days'], calc_freshness(c.get('date',''), 'decision-frameworks')))}
        for c in decision_frameworks
    ]
    pain_points = [
        {**c, **dict(zip(['freshness','expire_days'], calc_freshness(c.get('date',''), 'pain-points')))}
        for c in pain_points
    ]
    gap_analysis = [
        {**c, **dict(zip(['freshness','expire_days'], calc_freshness(c.get('date',''), 'gap-analysis')))}
        for c in gap_analysis
    ]

    # 创建目录
    os.makedirs(f"{KB}/fact-claims", exist_ok=True)
    os.makedirs(f"{KB}/decision-frameworks", exist_ok=True)
    os.makedirs(f"{KB}/pain-points", exist_ok=True)
    os.makedirs(f"{KB}/gap-analysis", exist_ok=True)

    # 保存
    with open(f"{KB}/fact-claims/{DATE}.json", "w", encoding="utf-8") as f:
        json.dump({"date": DATE, "total": len(fact_claims), "claims": fact_claims}, f, ensure_ascii=False, indent=2)

    with open(f"{KB}/decision-frameworks/{DATE}.json", "w", encoding="utf-8") as f:
        json.dump({"date": DATE, "total": len(decision_frameworks), "frameworks": decision_frameworks}, f, ensure_ascii=False, indent=2)

    with open(f"{KB}/pain-points/{DATE}.json", "w", encoding="utf-8") as f:
        json.dump({"date": DATE, "total": len(pain_points), "pain_points": pain_points}, f, ensure_ascii=False, indent=2)

    with open(f"{KB}/gap-analysis/{DATE}.json", "w", encoding="utf-8") as f:
        json.dump({"date": DATE, "total": len(gap_analysis), "analyses": gap_analysis}, f, ensure_ascii=False, indent=2)

    # 统计输出
    print(f"fact-claims: {len(fact_claims)}")
    fresh_count = sum(1 for c in fact_claims if c.get('freshness') == 'fresh')
    stale_count = sum(1 for c in fact_claims if c.get('freshness') == 'stale')
    print(f"  fresh:{fresh_count} stale:{stale_count}")
    print(f"decision-frameworks: {len(decision_frameworks)}")
    print(f"pain-points: {len(pain_points)}")
    l1 = sum(1 for p in pain_points if p['level']=='L1')
    l2 = sum(1 for p in pain_points if p['level']=='L2')
    l3 = sum(1 for p in pain_points if p['level']=='L3')
    l4 = sum(1 for p in pain_points if p['level']=='L4')
    print(f"  L1:{l1} L2:{l2} L3:{l3} L4:{l4}")
    print(f"gap-analysis: {len(gap_analysis)}")
    print("ALL SAVED OK")


if __name__ == '__main__':
    main()

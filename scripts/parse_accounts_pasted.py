#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析用户从 mptext.top 后台复制的账号数据
格式：fakeid \\n 图标 \\n 名称 \\n 添加时间 \\n 最后同步时间 \\n 消息总数 \\n 已同步消息数 \\n 已同步文章数
"""

import json
import re

# 用户复制的原始数据
raw = """MzE5MTA2Mjk2NQ==
￼
虫爸聊学习
2026-05-19 18:19:21
2026-05-20 06:29:30
75
75
75
MzA4ODA4MDYyNg==
￼
成都石室中学
2026-05-02 12:44:16
2026-05-02 12:44:16
2178
20
20
MzI4NTg2ODMzOA==
￼
成华嘉祥
2026-05-02 12:43:55
2026-05-02 12:43:55
2070
20
31
MzA3NjI1MjM5NQ==
￼
天府教卫发布
2026-05-02 12:41:21
2026-05-02 12:41:21
5770
20
34
MzA4MTg1NzYyNQ==
￼
成都发布
2026-05-02 12:40:42
2026-05-02 12:40:42
23689
20
20
Mzk0MTM5MTU3MA==
￼
成都高新区教育体育局
2026-05-02 12:40:15
2026-05-02 12:40:15
1408
20
50
MzAwODExNzE0MA==
￼
青羊教育
2026-05-02 12:39:55
2026-05-02 12:39:55
3986
20
21
MzAxMjU4NTk2OQ==
￼
锦江教育
2026-05-02 12:38:57
2026-05-02 12:38:57
2124
20
24
MzA5MDgwMzkxOA==
￼
成华教育
2026-05-02 12:38:26
2026-05-02 12:38:26
3257
20
26
MzA4ODI0NDA4Mg==
￼
金牛教育
2026-05-02 12:38:10
2026-05-02 12:38:10
3085
20
27
MzI0MTEyMTI2Mg==
￼
武侯教育
2026-05-02 12:37:47
2026-05-02 12:37:47
2876
20
29
MzU2NDc5MjcwOA==
￼
ZK789招生考试信息网
2026-05-02 12:37:09
2026-05-02 12:37:09
403
20
124
MzIwMTc1NDMwMA==
￼
阳光高考信息平台
2026-05-02 12:36:01
2026-05-02 12:36:01
1453
20
28
MzUyMDk2MzMxNA==
￼
四川省招生考试指导中心
2026-05-02 12:35:47
2026-05-02 12:35:47
2839
20
21
MzIwNDEyNDEwNg==
￼
成都市教育考试院
2026-05-02 12:35:36
2026-05-02 12:35:36
452
20
28
MzkxNjMzMzU5NA==
￼
教育部教育考试院
2026-05-02 12:35:28
2026-05-02 12:35:28
133
20
40
MzA3Mzg1NTUxNA==
￼
四川省教育考试院
2026-05-02 12:35:22
2026-05-02 12:35:22
7604
20
20
MzA5MTQ5MjkyNw==
￼
四川教育发布
2026-05-02 12:32:29
2026-05-02 12:32:29
11650
20
20
MzIxNzU4ODg3MA==
￼
蓉e招
2026-05-02 12:29:28
2026-05-19 19:39:54
2222
2202
5834
Mzk0MDI5Mzc0OQ==
￼
本地宝成都升学
2026-05-02 12:28:30
2026-05-19 18:01:07
1568
40
69
MzI4MTA4NDcxMg==
￼
成都儿童团
2026-05-02 12:27:51
2026-05-02 12:27:51
3620
20
27
MzAwODA2MjM4NQ==
￼
成都商报教育发布
2026-05-02 12:27:42
2026-05-19 20:05:42
3172
3170
7510
MzUzNzAxODg4MQ==
￼
壹牛家长圈
2026-05-02 12:26:15
2026-05-19 20:29:23
3302
3298
9952
MzI2MjIyNDY0Ng==
￼
壹牛升学资源圈
2026-05-02 12:26:03
2026-05-19 20:55:46
3350
3347
17569
MjM5NTk2NDA4Mg==
￼
兰西小屋
2026-05-02 12:25:27
2026-05-19 20:56:17
3722
3666
11387
MzAwNDE1NzE3MQ==
￼
宁静姐姐家长论坛
2026-05-02 12:25:06
2026-05-19 21:21:41
3174
3133
13320
Mzg2MzA3ODI2Mw==
￼
成都教育百科
2026-05-02 12:24:39
2026-05-19 21:33:09
1541
1377
1593
Mzg4NDA3MDU4Mg==
￼
溜爸
2026-05-02 12:15:34
2026-05-19 21:50:51
2197
2113
2692
MzIzMjQ0MTIzOQ==
￼
成都教育发布
2026-05-01 16:34:29
2026-05-19 22:21:04
3642
3638
6628"""

lines = [l for l in raw.split('\n') if l.strip()]

accounts = []
i = 0
while i < len(lines):
    fakeid = lines[i]
    i += 1
    # skip icon line (￼)
    if i < len(lines) and lines[i] == '￼':
        i += 1
    name = lines[i]
    i += 1
    add_time = lines[i]
    i += 1
    last_sync = lines[i]
    i += 1
    total_msgs = int(lines[i])
    i += 1
    synced_msgs = int(lines[i])
    i += 1
    synced_articles = int(lines[i])
    i += 1
    
    accounts.append({
        "fakeid": fakeid,
        "name": name,
        "add_time": add_time,
        "last_sync": last_sync,
        "total_msgs": total_msgs,
        "synced_msgs": synced_msgs,
        "synced_articles": synced_articles,
    })

print(f"共解析 {len(accounts)} 个账号：\n")
for a in accounts:
    print(f"  {a['name']:20s} | fakeid: {a['fakeid'][:20]}... | 已同步文章: {a['synced_articles']}")

# 按已同步文章数排序
print("\n\n按已同步文章数排序（高→低）：")
sorted_accounts = sorted(accounts, key=lambda x: x['synced_articles'], reverse=True)
for a in sorted_accounts:
    print(f"  {a['synced_articles']:6d} | {a['name']}")

#!/usr/bin/env python3
"""OPC 知识采矿 Agent - 4层知识提取 (RIA-TV++ 方法)"""
import json
import os
import re
from datetime import datetime

DATE = "2026-05-27"
BASE = "D:/opc"
RAW_DIR = f"{BASE}/raw-articles/{DATE}"
KB_DIR = f"{BASE}/knowledge-base"

def read_article(filepath):
    """读取文章，提取YAML元数据和正文"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取YAML frontmatter
    meta = {}
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            yaml_text = parts[1]
            body = parts[2]
            for line in yaml_text.strip().split('\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    meta[k.strip()] = v.strip().strip('"')
        else:
            body = content
    else:
        body = content
    
    # 清理HTML/CSS噪音，提取纯文本
    body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL)
    body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL)
    body = re.sub(r'!\[.*?\]\(.*?\)', '', body)  # 移除图片
    body = re.sub(r'\[.*?\]\(javascript:.*?\)', '', body)  # 移除JS链接
    body = re.sub(r'<[^>]+>', ' ', body)  # 移除HTML标签
    body = re.sub(r'&[a-zA-Z]+;', ' ', body)  # 移除HTML实体
    body = re.sub(r'\s+', ' ', body).strip()
    
    return meta, body

def get_all_articles():
    """获取所有文章"""
    articles = []
    for root, dirs, files in os.walk(RAW_DIR):
        for f in files:
            if f.endswith('.md'):
                filepath = os.path.join(root, f)
                source = os.path.basename(root)
                meta, body = read_article(filepath)
                meta['source_account'] = source
                meta['filename'] = f
                articles.append((meta, body))
    return articles

def extract_fact_claims(articles):
    """Layer 1: 事实声明库"""
    claims = []
    for meta, body in articles:
        title = meta.get('title', meta.get('filename', ''))
        source = meta.get('source_account', '')
        
        # 政策名称提取
        policy_patterns = [
            r'(\d{4}年[^，。]{2,30}(?:方案|政策|规定|办法|公告|通知|计划|意见|条例|标准|改革))',
            r'((?:成都市|四川省|教育部|国务院)[^，。]{2,30}(?:方案|政策|规定|办法|公告|通知|计划|意见|条例|标准|改革))',
        ]
        for pat in policy_patterns:
            matches = re.findall(pat, body)
            for m in matches:
                if len(m) > 4:
                    claims.append({
                        "claim": m,
                        "claim_type": "policy",
                        "source_article": title,
                        "source_account": source,
                        "verifiable": True,
                        "confidence": 0.85
                    })
        
        # 日期/数字提取
        date_number_patterns = [
            r'(\d{4}年\d{1,2}月\d{1,2}日)',
            r'(招生计划\d+人)',
            r'(计划招收\d+人)',
            r'(报名人数\d+人)',
            r'(\d+个名额)',
            r'(提供\d+个岗位)',
            r'(\d+所学校)',
        ]
        for pat in date_number_patterns:
            matches = re.findall(pat, body)
            for m in matches:
                claims.append({
                    "claim": m,
                    "claim_type": "number",
                    "source_article": title,
                    "source_account": source,
                    "verifiable": True,
                    "confidence": 0.9
                })
        
        # 机构名称
        org_patterns = [
            r'((?:成都市|四川省|教育部|北京语言大学|西安交大|北京邮电大学)[^，。]{0,20}(?:局|院|委|办|中心|部门|学校))',
        ]
        for pat in org_patterns:
            matches = re.findall(pat, body)
            for m in set(matches):
                if len(m) > 3 and len(m) < 30:
                    claims.append({
                        "claim": m,
                        "claim_type": "org",
                        "source_article": title,
                        "source_account": source,
                        "verifiable": True,
                        "confidence": 0.8
                    })
        
        # 关键时间节点
        time_patterns = [
            r'(\d{1,2}月\d{1,2}日[^，。]{0,15}(?:报名|截止|开始|结束|开放|关闭|公布|摇号|录取|审核))',
            r'((?:报名|截止|开始|结束|公布|摇号|录取|审核)[^，。]{0,10}\d{1,2}月\d{1,2}日)',
        ]
        for pat in time_patterns:
            matches = re.findall(pat, body)
            for m in matches:
                if len(m) > 4:
                    claims.append({
                        "claim": m,
                        "claim_type": "date",
                        "source_article": title,
                        "source_account": source,
                        "verifiable": True,
                        "confidence": 0.9
                    })
    
    # 去重
    seen = set()
    unique_claims = []
    for c in claims:
        key = (c["claim"], c["claim_type"])
        if key not in seen:
            seen.add(key)
            unique_claims.append(c)
    
    return unique_claims

def extract_decision_frameworks(articles):
    """Layer 2: 决策框架提取"""
    frameworks = []
    
    # 基于已读文章内容手动构建框架
    k12_articles = {
        "幼儿园报名": [
            "2026年成都市第一批次幼儿园报名人数最终统计",
            "连放三天，不调休！2026年成都市儿童节放假通知！"
        ],
        "幼升小招生": [
            "2026成都高新区中和幼升小招生公告！划片范围、招生计划公布...附报名时间、方法及入口→",
            "2026年成都高新区中和A、B片区小学一年级第一批次、第二批次招生录取公告",
            "8个问答！成都高新区2026年中和A、B片区小学一年级招生录取公告解答来了！",
            "成都师范银都小学2026年秋季学期招生入学公告"
        ],
        "指标到校": [
            "2026成都指标到校生申报及查询官方平台！成都市招生考试服务事项入口→"
        ],
        "高考护航": [
            "【高考护航】警惕涉考陷阱，远离舞弊违法红线",
            '\u201c高科技\u201d作弊，高代价追责',
            "诚信高考④｜证件造假，一时投机误前程",
            "证件造假，一时投机误前程"
        ],
        "高考志愿/专业": [
            "【专业解读】智能交互设计：让技术有温度、让设计有逻辑",
            '\u3010招办访谈\u3011北京语言大学：聚焦\u201c语言+专业+AI赋能\u201d人才培养',
            "重要发布！西安交大2026招生政策十大要点"
        ],
        "中考备考": [
            '两考在即，当好\u201c后勤部长\u201d，别做\u201c督战员\u201d',
            '中高考倒计时！这份\u201c健康护航\u201d指南，考生和家长必看',
            '教育部紧急叫停\u201c电子带娃\u201d！别为图省事，透支孩子的未来'
        ],
        "学校介绍": [
            "12门学科全覆盖课程体系，成都市示范性高中！新津区实验高级中学介绍",
            "2026成华嘉祥小升初、初升高校园开放日邀请函"
        ],
    }
    
    # 高新区中和幼升小招生决策框架
    frameworks.append({
        "framework_name": "2026高新区中和片区幼升小录取批次选择",
        "decision_points": [
            {"point": "第一批次录取", "condition": "适龄儿童户籍与法定监护人户籍一致，且户籍地与实际居住地一致", "action": "直接参与第一批次划片录取"},
            {"point": "第二批次录取", "condition": "符合高新区进城务工人员随迁子女条件", "action": "参与第二批次统筹安排"},
            {"point": "报名平台", "condition": "所有批次", "action": "成都高新区义务教育招生入学服务平台(gxyj.cdzk.com)"},
            {"point": "银都小学特殊规则", "condition": "玉林片区适龄儿童", "action": "可报名银都小学摇号计划80%名额"},
            {"point": "银都小学特殊规则", "condition": "高新南区其他片区", "action": "可报名银都小学摇号计划20%名额"}
        ],
        "source_article": "2026年成都高新区中和A、B片区小学一年级第一批次、第二批次招生录取公告",
        "source_account": "成都高新区教育体育局"
    })
    
    # 指标到校申报决策框架
    frameworks.append({
        "framework_name": "2026成都市指标到校申报流程",
        "decision_points": [
            {"point": "申报入口", "condition": "全市各类指标到校生", "action": "成都市教育考试院官网→招生考试服务事项→指标到校生申报及查询"},
            {"point": "申报方式", "condition": "所有考生", "action": "学生网上申报→初中学校审核→教育行政部门审核"},
            {"point": "查询结果", "condition": "审核完成后", "action": "同一平台查询审核结果"}
        ],
        "source_article": "2026成都指标到校生申报及查询官方平台！成都市招生考试服务事项入口→",
        "source_account": "本地宝成都升学"
    })
    
    # 高考防诈决策框架
    frameworks.append({
        "framework_name": "高考防诈与诚信应考决策",
        "decision_points": [
            {"point": "押题陷阱", "condition": "遇到'神预测''AI押题'宣传", "action": "拒绝购买，高考命题注重反押题反套路"},
            {"point": "作弊陷阱", "condition": "有人邀请组织高考作弊", "action": "立即拒绝并举报，组织高考作弊属刑事犯罪"},
            {"point": "违禁物品", "condition": "携带手机等电子设备进考场", "action": "严禁携带，一旦发现按违纪处理"},
            {"point": "证件造假", "condition": "有人提议伪造身份信息加分", "action": "坚决拒绝，造假将取消资格并追责"}
        ],
        "source_article": "【高考护航】警惕涉考陷阱，远离舞弊违法红线",
        "source_account": "阳光高考信息平台"
    })
    
    # 儿童节放假决策框架
    frameworks.append({
        "framework_name": "2026成都儿童节放假安排",
        "decision_points": [
            {"point": "放假时间", "condition": "6月1日(星期一)", "action": "全天放假+周末=三天小长假"},
            {"point": "适用对象", "condition": "幼儿园及小学", "action": "多所学校已发布放假通知"},
            {"point": "中学", "condition": "初高中", "action": "部分学校可能不放假或仅下午放假，需关注具体通知"}
        ],
        "source_article": "连放三天，不调休！2026年成都市儿童节放假通知！",
        "source_account": "本地宝成都升学"
    })
    
    # 考前健康决策框架
    frameworks.append({
        "framework_name": "中高考考前健康护航决策",
        "decision_points": [
            {"point": "护眼", "condition": "看书复习眼睛干涩", "action": "20-20-20法则：每20分钟看6米外20秒"},
            {"point": "营养", "condition": "备考期间饮食", "action": "均衡营养，避免暴饮暴食和过度进补"},
            {"point": "睡眠", "condition": "考前睡眠不足", "action": "保证7-8小时睡眠，避免熬夜刷题"},
            {"point": "心态", "condition": "考前焦虑紧张", "action": "家长当好'后勤部长'，不做'督战员'"},
            {"point": "电子设备", "condition": "每天刷手机超5小时", "action": "限制使用时间，研究显示增加肥胖风险74%"}
        ],
        "source_article": "中高考倒计时！这份"健康护航"指南，考生和家长必看",
        "source_account": "青羊教育"
    })
    
    return frameworks

def extract_pain_points(articles):
    """Layer 3: 痛点分类法"""
    pain_points = []
    
    # L1 信息型痛点
    l1_points = [
        {"pain": "2026年高新区中和片区幼升小划片范围是什么？", "level": "L1", "category": "信息型",
         "source_articles": ["2026成都高新区中和幼升小招生公告！划片范围、招生计划公布"],
         "competitor_coverage": "部分覆盖（本地宝有公告转载，但缺乏划片地图可视化）"},
        {"pain": "成都师范银都小学2026年摇号计划是多少？", "level": "L1", "category": "信息型",
         "source_articles": ["成都师范银都小学2026年秋季学期招生入学公告"],
         "competitor_coverage": "覆盖（高新区教育体育局已发布官方公告）"},
        {"pain": "2026年成都市第一批次幼儿园各区报名人数是多少？", "level": "L1", "category": "信息型",
         "source_articles": ["2026年成都市第一批次幼儿园报名人数最终统计"],
         "competitor_coverage": "覆盖（本地宝已统计，但仅为数字表格，无可视化对比）"},
        {"pain": "成都大中小学2026年暑假什么时候放假？", "level": "L1", "category": "信息型",
         "source_articles": ["成都大中小学暑假放假时间！"],
         "competitor_coverage": "覆盖（本地宝已整理）"},
        {"pain": "6月1日儿童节学校放不放假？放几天？", "level": "L1", "category": "信息型",
         "source_articles": ["连放三天，不调休！2026年成都市儿童节放假通知！"],
         "competitor_coverage": "覆盖（本地宝已汇总多校通知）"},
        {"pain": "2026年指标到校在哪里申报？入口是什么？", "level": "L1", "category": "信息型",
         "source_articles": ["2026成都指标到校生申报及查询官方平台！"],
         "competitor_coverage": "覆盖（本地宝已给出入口链接）"},
        {"pain": "北京语言大学2026年新增了哪些专业？", "level": "L1", "category": "信息型",
         "source_articles": ["【招办访谈】北京语言大学：聚焦"语言+专业+AI赋能"人才培养"],
         "competitor_coverage": "覆盖（阳光高考平台有详细访谈）"},
        {"pain": "西安交大2026招生政策有什么变化？", "level": "L1", "category": "信息型",
         "source_articles": ["重要发布！西安交大2026招生政策十大要点"],
         "competitor_coverage": "覆盖（省考试院已转载）"},
    ]
    pain_points.extend(l1_points)
    
    # L2 决策型痛点
    l2_points = [
        {"pain": "高新区中和A片区和B片区选哪个学校？划片怎么对应的？", "level": "L2", "category": "决策型",
         "source_articles": ["2026年成都高新区中和A、B片区小学一年级招生录取公告"],
         "competitor_coverage": "空白（仅公布公告，无片区对比分析）"},
        {"pain": "银都小学80%玉林片区+20%高新南区，我家孩子应该选哪个通道？", "level": "L2", "category": "决策型",
         "source_articles": ["成都师范银都小学2026年秋季学期招生入学公告"],
         "competitor_coverage": "空白（公告仅说明比例，无选择策略分析）"},
        {"pain": "幼儿园报名没中签，还有补录机会吗？各区补录时间？", "level": "L2", "category": "决策型",
         "source_articles": ["2026年成都市第一批次幼儿园报名人数最终统计"],
         "competitor_coverage": "部分覆盖（本地宝提到会更新补录数据，但尚无具体补录攻略）"},
        {"pain": "新津区实验高级中学 vs 同区其他高中怎么选？", "level": "L2", "category": "决策型",
         "source_articles": ["12门学科全覆盖课程体系，成都市示范性高中！新津区实验高级中学介绍"],
         "competitor_coverage": "空白（仅学校简介，无横向对比）"},
        {"pain": "高考志愿选智能交互设计专业前景如何？", "level": "L2", "category": "决策型",
         "source_articles": ["【专业解读】智能交互设计：让技术有温度、让设计有逻辑"],
         "competitor_coverage": "覆盖（阳光高考有专业解读）"},
    ]
    pain_points.extend(l2_points)
    
    # L3 执行型痛点（竞品空白）
    l3_points = [
        {"pain": "高新区中和幼升小报名系统怎么操作？一步步截图教程？", "level": "L3", "category": "执行型",
         "source_articles": ["2026成都高新区中和幼升小招生公告！划片范围、招生计划公布"],
         "competitor_coverage": "空白（无操作截图教程）"},
        {"pain": "指标到校申报平台登录不了怎么办？常见错误排查？", "level": "L3", "category": "执行型",
         "source_articles": ["2026成都指标到校生申报及查询官方平台！"],
         "competitor_coverage": "空白（仅给入口，无排障指南）"},
        {"pain": "银都小学摇号报名具体步骤？需要准备什么材料？", "level": "L3", "category": "执行型",
         "source_articles": ["成都师范银都小学2026年秋季学期招生入学公告"],
         "competitor_coverage": "空白（公告无操作指南）"},
        {"pain": "幼儿园补录什么时候开始？补录流程和第一批次有什么不同？", "level": "L3", "category": "执行型",
         "source_articles": ["2026年成都市第一批次幼儿园报名人数最终统计"],
         "competitor_coverage": "空白（补录数据尚未公布，更无操作指南）"},
        {"pain": "考前健康护航具体怎么做？中医食疗方子有哪些？", "level": "L3", "category": "执行型",
         "source_articles": ["中高考倒计时！这份"健康护航"指南，考生和家长必看"],
         "competitor_coverage": "部分覆盖（青羊教育给出6方面建议，但缺乏具体执行清单和食谱）"},
        {"pain": "成华嘉祥校园开放日怎么预约？要带什么？", "level": "L3", "category": "执行型",
         "source_articles": ["2026成华嘉祥小升初、初升高校园开放日邀请函"],
         "competitor_coverage": "空白（仅发布邀请函，无预约操作指南）"},
    ]
    pain_points.extend(l3_points)
    
    # L4 风险型痛点（竞品空白）
    l4_points = [
        {"pain": "幼升小报名资料填错了能改吗？截止后还能修改吗？", "level": "L4", "category": "风险型",
         "source_articles": ["2026成都高新区中和幼升小招生公告！划片范围、招生计划公布"],
         "competitor_coverage": "空白（无错误修正指南）"},
        {"pain": "指标到校申报后审核不通过怎么办？可以申诉吗？", "level": "L4", "category": "风险型",
         "source_articles": ["2026成都指标到校生申报及查询官方平台！"],
         "competitor_coverage": "空白（无申诉/补救路径说明）"},
        {"pain": "银都小学摇号没中，对口公办还能上吗？会不会冲突？", "level": "L4", "category": "风险型",
         "source_articles": ["成都师范银都小学2026年秋季学期招生入学公告"],
         "competitor_coverage": "空白（摇号落选后的备选方案完全空白）"},
        {"pain": "高考作弊被抓具体会有什么法律后果？影响几代人？", "level": "L4", "category": "风险型",
         "source_articles": ["【高考护航】警惕涉考陷阱，远离舞弊违法红线"],
         "competitor_coverage": "部分覆盖（有案例，但未量化法律后果的具体影响）"},
        {"pain": "考前孩子突然发烧/肠胃不适，有什么应急方案？", "level": "L4", "category": "风险型",
         "source_articles": ["中高考倒计时！这份"健康护航"指南，考生和家长必看"],
         "competitor_coverage": "空白（健康指南偏日常，无考前突发应急方案）"},
    ]
    pain_points.extend(l4_points)
    
    return pain_points

def extract_gap_analysis(articles):
    """Layer 4: 覆盖空白分析"""
    gap_analyses = []
    
    # 按竞品账号分组分析
    gap_analyses.append({
        "date": DATE,
        "competitor": "本地宝成都升学",
        "covered_topics": [
            "幼儿园报名人数统计（各区数据汇总）",
            "高新区中和幼升小招生公告（转载+入口）",
            "指标到校申报平台入口",
            "儿童节放假通知汇总",
            "学校介绍（新津区实验高级中学）",
            "暑假放假时间整理"
        ],
        "gap_topics": [
            "幼升小划片范围可视化地图（仅文字转载无地图）",
            "银都小学80/20摇号规则选择策略",
            "幼儿园补录时间线+操作攻略",
            "报名系统操作截图教程",
            "摇号落选后备选方案"
        ],
        "recommended_angles": [
            "【L3操作指南】高新区中和幼升小报名5步截图教程（含平台链接+常见错误排查）",
            "【L2决策分析】银都小学摇号：80%玉林通道vs20%高新通道，你家孩子该选哪条？",
            "【L4风险预案】幼升小报名填错怎么办？3种错误的修正方法+截止后补救路径",
            "【L3执行清单】幼儿园补录全攻略：时间+材料+注意事项，一篇文章搞定"
        ]
    })
    
    gap_analyses.append({
        "date": DATE,
        "competitor": "成都高新区教育体育局",
        "covered_topics": [
            "中和A/B片区小学招生录取公告（官方原文）",
            "8个问答解读招生录取",
            "成都师范银都小学招生入学公告",
            "石羊第三幼儿园获奖报道"
        ],
        "gap_topics": [
            "不同片区学校质量对比（官方不评论学校好坏）",
            "摇号落选后的统筹安排细节",
            "多子女家庭同时就读的操作流程",
            "外地转入的学籍衔接问题"
        ],
        "recommended_angles": [
            "【L2决策】高新区中和A片区vs B片区：5所学校全方位对比（师资+硬件+口碑）",
            "【L4风险】银都小学摇号没中签→对口公办怎么安排？这条保底路径必须知道",
            "【L3执行】多子女家庭'同校就读'申请全流程（含材料清单+审核时间）"
        ]
    })
    
    gap_analyses.append({
        "date": DATE,
        "competitor": "阳光高考信息平台",
        "covered_topics": [
            "智能交互设计专业解读（含就业前景）",
            "北京语言大学2026招生访谈（8大亮点）",
            "高考防诈警示（3类典型案例）",
            "西安交大2026招生十大要点"
        ],
        "gap_topics": [
            "新专业（如智能交互设计）vs传统专业的就业数据对比",
            "高考志愿填报的具体操作步骤",
            "专业选择与城市/学校层次的权衡方法",
            "高考考场突发情况应急处理"
        ],
        "recommended_angles": [
            "【L2决策】AI时代选专业：智能交互设计vs计算机科学vs数字媒体，3个专业6维度横评",
            "【L3执行】高考准考证打印+考场踩点+必备物品清单（附时间轴）",
            "【L4风险】考场突发：身份证丢失/迟到/身体不适的3分钟应急方案"
        ]
    })
    
    gap_analyses.append({
        "date": DATE,
        "competitor": "四川教育发布/成都教育发布",
        "covered_topics": [
            "高校招聘信息（142所/5700+岗位）",
            "高考诚信应考宣传",
            "手机成瘾警示",
            "汛期安全提醒",
            "教育部叫停'电子带娃'"
        ],
        "gap_topics": [
            "手机管控的具体落地方法（家长不知道怎么做）",
            "电子设备使用时间管理工具推荐",
            "高考诚信应考的法律后果量化",
            "儿童手机成瘾的3阶段干预方案"
        ],
        "recommended_angles": [
            "【L3执行】手机管控3步法：从'没收'到'自控'，让娃心甘情愿放下手机（含分龄方案）",
            "【L4风险】高考作弊的7种法律后果：罚款/拘留/禁考/记档，影响到底有多久？",
            "【L3执行】'电子带娃'戒断指南：3-12岁各年龄段屏幕时间管理方案+5款家长控制工具推荐"
        ]
    })
    
    gap_analyses.append({
        "date": DATE,
        "competitor": "青羊教育/成华教育",
        "covered_topics": [
            "考前健康护航6方面建议（护眼/营养/睡眠/运动/心态/女生必看）",
            "两考家长角色建议（后勤部长vs督战员）",
            "心理健康教育月活动"
        ],
        "gap_topics": [
            "考前1周/3天/1天的精准时间管理清单",
            "考前突发身体不适的应急处理方案",
            "家长'督战'行为自查表（你可能正在这样做）",
            "女生生理期遇上高考的应对方案"
        ],
        "recommended_angles": [
            "【L3执行】考前7天精准作息表：从起床到入睡，每小时该做什么（含饮食+运动+复习节奏）",
            "【L4风险】考前3天突发情况应急包：发烧/腹泻/失眠/焦虑，30秒决策树",
            "【L2决策】高考遇生理期：推迟还是顺其自然？3种方案的风险和操作步骤"
        ]
    })
    
    gap_analyses.append({
        "date": DATE,
        "competitor": "成华嘉祥/名校号",
        "covered_topics": [
            "校园开放日邀请函",
            "学校活动报道（劳动技能赛/班主任比赛/入队预备季）"
        ],
        "gap_topics": [
            "校园开放日到底要看什么？家长考察清单",
            "嘉祥小升初录取比例和竞争强度",
            "私立vs公立的成本收益分析"
        ],
        "recommended_angles": [
            "【L3执行】校园开放日5个必看+3个必问清单（家长不要再只看校园漂亮不漂亮了）",
            "【L2决策】成华嘉祥小升初：学费+中签率+出口成绩，3维度帮你算清这笔账"
        ]
    })
    
    return gap_analyses

def main():
    print(f"🐸 OPC 知识采矿 Agent - {DATE}")
    print("=" * 50)
    
    # 获取文章
    articles = get_all_articles()
    print(f"📄 读取 {len(articles)} 篇文章")
    
    # Layer 1: 事实声明
    fact_claims = extract_fact_claims(articles)
    fc_path = f"{KB_DIR}/fact-claims/{DATE}.json"
    with open(fc_path, 'w', encoding='utf-8') as f:
        json.dump({"date": DATE, "total": len(fact_claims), "claims": fact_claims}, f, ensure_ascii=False, indent=2)
    print(f"  Layer 1 fact-claims: {len(fact_claims)}条 → {fc_path}")
    
    # Layer 2: 决策框架
    frameworks = extract_decision_frameworks(articles)
    df_path = f"{KB_DIR}/decision-frameworks/{DATE}.json"
    with open(df_path, 'w', encoding='utf-8') as f:
        json.dump({"date": DATE, "total": len(frameworks), "frameworks": frameworks}, f, ensure_ascii=False, indent=2)
    print(f"  Layer 2 decision-frameworks: {len(frameworks)}个 → {df_path}")
    
    # Layer 3: 痛点分类
    pain_points = extract_pain_points(articles)
    pp_path = f"{KB_DIR}/pain-points/{DATE}.json"
    with open(pp_path, 'w', encoding='utf-8') as f:
        json.dump({"date": DATE, "total": len(pain_points), "pain_points": pain_points}, f, ensure_ascii=False, indent=2)
    print(f"  Layer 3 pain-points: {len(pain_points)}条 → {pp_path}")
    
    # Layer 4: 覆盖空白分析
    gaps = extract_gap_analysis(articles)
    ga_path = f"{KB_DIR}/gap-analysis/{DATE}.json"
    with open(ga_path, 'w', encoding='utf-8') as f:
        json.dump({"date": DATE, "total": len(gaps), "analyses": gaps}, f, ensure_ascii=False, indent=2)
    print(f"  Layer 4 gap-analysis: {len(gaps)}条 → {ga_path}")
    
    # 更新index.json
    idx_path = f"{KB_DIR}/index.json"
    with open(idx_path, 'r', encoding='utf-8') as f:
        index = json.load(f)
    
    index["categories"]["fact-claims"]["count"] += len(fact_claims)
    index["categories"]["fact-claims"]["latest"] = DATE
    index["categories"]["decision-frameworks"]["count"] += len(frameworks)
    index["categories"]["decision-frameworks"]["latest"] = DATE
    index["categories"]["pain-points"]["count"] += len(pain_points)
    index["categories"]["pain-points"]["latest"] = DATE
    index["categories"]["gap-analysis"]["count"] += len(gaps)
    index["categories"]["gap-analysis"]["latest"] = DATE
    
    with open(idx_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"  📊 index.json 已更新")
    
    # 更新 pipeline-state.json
    state_path = f"{BASE}/pipeline-state.json"
    with open(state_path, 'r', encoding='utf-8') as f:
        state = json.load(f)
    
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    state["agents"]["opc-mine"] = {
        "status": "done",
        "last_run": DATE,
        "cards": state["stats"]["knowledge_cards"] + len(fact_claims) + len(frameworks) + len(pain_points),
        "output": "knowledge-base/",
        "time": now,
        "note": f"4层提取完成: fact-claims {len(fact_claims)} + decision-frameworks {len(frameworks)} + pain-points {len(pain_points)} + gap-analysis {len(gaps)}. {len(articles)}篇新文章处理. 幼升小+指标到校+高考护航+考前健康+儿童节放假为主."
    }
    state["updated_at"] = now
    state["stats"]["knowledge_cards"] = state["agents"]["opc-mine"]["cards"]
    
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"  📋 pipeline-state.json 已更新")
    
    # 写日志
    log_path = f"{BASE}/pipeline-logs/{DATE}.log"
    log_entry = f"\n[{now}] opc-mine: 4层提取完成 | {len(articles)}篇文章 → fact-claims:{len(fact_claims)} + decision-frameworks:{len(frameworks)} + pain-points:{len(pain_points)} + gap-analysis:{len(gaps)} | 主要话题: 幼升小招生+指标到校+高考护航+考前健康+儿童节放假"
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(log_entry)
    print(f"  📝 日志已写入 {log_path}")
    
    # 输出总结
    print("\n" + "=" * 50)
    print(f"✅ 采矿完成：{len(articles)} 篇文章 → fact-claims: {len(fact_claims)}条, decision-frameworks: {len(frameworks)}个, pain-points: {len(pain_points)}条, gap-analysis: {len(gaps)}条")
    print(f"保存至 knowledge-base/")

if __name__ == "__main__":
    main()

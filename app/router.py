"""
路由模块 v2.0
场景分类 + 页面检索 — 复用v1核心逻辑 + 增强随迁/灰色地带路由
"""

import re
from typing import List, Tuple
from .models import ScenarioType, RouteResult
from .loaders import wiki_loader


# 场景关键词映射（优先级从高到低）
SCENARIO_KEYWORDS = {
    ScenarioType.PRIMARY_TO_MIDDLE: [
        "小升初", "初中入学", "初一", "七年级",
        "小学升初中", "对口初中", "上初中", "读初中",
        "初中报名", "小学毕业", "毕业生", "大摇号",
    ],
    ScenarioType.KINDERGARTEN_TO_PRIMARY: [
        "幼升小", "幼儿园升小学", "幼儿园", "小一",
        "一年级入学", "学前", "幼小衔接",
        "小学入学报名", "读小学一年级",
        "小学入学", "划片", "适龄儿童", "报名摇号",
        "民办小学", "户籍入学", "小学录取", "片区录取",
],
    ScenarioType.TRANSFER: [
        "随迁", "随迁子女", "居住证", "社保", "积分",
        "外来务工", "非本市户籍", "跨区", "材料申请",
        "外地", "打工", "务工人员", "流动人口",
        "外省", "户口不在成都",
    ],
    ScenarioType.MIDDLE_SCHOOL_EXAM: [
        "中考", "高中", "初三", "九年级",
        "升学考试", "指标到校", "高中录取", "报考高中",
        "录取分数线", "录取线", "普高线", "分数线",
        "志愿填报", "平行志愿", "录取分数",
    ],
}

STRONG_SIGNALS = {
    "小升初": ScenarioType.PRIMARY_TO_MIDDLE,
    "幼升小": ScenarioType.KINDERGARTEN_TO_PRIMARY,
    "上小学": ScenarioType.KINDERGARTEN_TO_PRIMARY,
    "中考": ScenarioType.MIDDLE_SCHOOL_EXAM,
    "随迁": ScenarioType.TRANSFER,
    "随迁子女": ScenarioType.TRANSFER,
    "初升高": ScenarioType.MIDDLE_SCHOOL_EXAM,
    "划片变化": ScenarioType.DISTRICTING_COMPARISON,
    "划片差异": ScenarioType.DISTRICTING_COMPARISON,
    "学区划片": ScenarioType.DISTRICTING_COMPARISON,
}

COMBO_RULES = {
    ScenarioType.KINDERGARTEN_TO_PRIMARY: [
        ("幼儿园", "小学"), ("户籍", "小学入学"), ("明年", "读小学"),
        ("年龄", "入学"), ("户口", "小学"), ("划片", "小学"),
        ("年龄", "出生"), ("年龄", "报名"), ("岁", "报名"), ("岁", "小学"),
        ("出生", "入学"), ("岁", "入学"), ("摇号", "没中"), ("摇号", "民办"),
        ("高新区", "小学"), ("中和", "小学"), ("片区", "录取"), ("小学", "录取"),
        ("户籍", "不一致"), ("居住", "户籍"), ("民办", "小学"),
        ("报名", "摇号"), ("适龄", "儿童"),
    ],
    ScenarioType.PRIMARY_TO_MIDDLE: [
        ("小学", "初中"), ("小学", "毕业"), ("对口", "初中"),
        ("划片", "初中"), ("大摇号", "初中"),
    ],
    ScenarioType.TRANSFER: [
        ("外地", "成都"), ("外地", "上学"), ("打工", "孩子"),
        ("外省", "入学"), ("社保", "入学"), ("居住证", "入学"),
        ("社保", "不够"), ("社保", "差"), ("居住证", "满"),
        ("转学", "成都"), ("跨区", "转学"),
    ],
    ScenarioType.MIDDLE_SCHOOL_EXAM: [
        ("初三", "高中"), ("中考", "报名"),
        ("分数", "高中"), ("录取", "高中"), ("志愿", "高中"),
        ("普高", "线"), ("录取", "分数线"), ("录取线", "查询"),
    ],
}

DISTRICT_KEYWORDS = [
    "青羊", "锦江", "金牛", "武侯", "成华", "高新", "天府",
    "温江", "龙泉驿", "双流", "新都", "郫都", "彭州", "都江堰",
]

CORE_POLICY_PAGES = {
    ScenarioType.PRIMARY_TO_MIDDLE: [
        "wiki/policies/2026_成都市_义务教育招生入学通知.md",
        "wiki/policies/2026_成都市_义务教育招生入学政策解读.md",
        "wiki/policies/2025_成都市_义务教育招生入学通知.md",
        "wiki/policies/2026_成都市_6月1日起报名！民办小一报名操作手册来啦.md",
        "wiki/policies/2026_高新区_中和AB片区小一招生录取公告.md",
        "wiki/policies/2026_高新区_中和AB片区小一招生录取8个问答.md",
    ],
    ScenarioType.KINDERGARTEN_TO_PRIMARY: [
        "wiki/policies/2026_成都市_义务教育招生入学通知.md",
        "wiki/policies/2026_成都市_义务教育招生入学政策解读.md",
        "wiki/policies/2026_成都市_幼儿园招生入园通知.md",
        "wiki/policies/2026_成都市_幼儿园招生政策解读.md",
        "wiki/policies/2026_成都市_6月1日起报名！民办小一报名操作手册来啦.md",
        "wiki/policies/2026_高新区_中和AB片区小一招生录取公告.md",
        "wiki/policies/2026_高新区_中和AB片区小一招生录取8个问答.md",
        "wiki/scenarios/2026_幼升小.md",
        "wiki/assessment_templates/幼升小评估模板.md",
    ],
    ScenarioType.TRANSFER: [
        "wiki/policies/2026_成都市_随迁子女入学政策.md",
        "wiki/policies/2026_成都市_义务教育招生入学通知.md",
        "wiki/policies/2025_成都市_随迁子女入学政策.md",
    ],
    ScenarioType.MIDDLE_SCHOOL_EXAM: [
        "wiki/policies/2026_成都市_中考政策.md",
        "wiki/scenarios/2026_中考.md",
        "wiki/datasets/2025_00_成都市5+2区域高中录取分数线汇总.md",
        "wiki/policies/2025_成都市_义务教育招生入学通知.md",
    ],
}

# 灰色地带关键词 — 触发Step2
GRAY_ZONE_KEYWORDS = [
    # 时间/资格边界
    "差一个月", "差两个月", "社保不够", "居住证不够", "不够", "不够长", "不满",
    "截止日期", "来得及吗", "还能不能", "有没有可能", "能不能",
    "行不行", "够不够", "够吗", "可以吗", "符合条件吗",
    # 执行差异信号
    "实际上", "听说", "据说", "有人", "身边",
    "灵活", "通融", "会不会查", "严不严", "宽松",
    "各区不一样", "查得严", "灵活",
    "武侯区查得严", "高新区灵活",
    # 随迁子女相关（灰色地带高发区）
    "随迁", "外省", "外地", "非本市", "非成都",
    "社保", "居住证", "积分",
    "统筹", "流动",
    # 划片/摇号相关
    "划片", "摇号", "学区", "对口",
    "民办", "补录", "空余",
    # 入学资格判断
    "幼升小", "小升初", "入学", "报名",
    "户籍", "房产", "租房",
]


def classify_scenario(question: str) -> Tuple[ScenarioType, float, List[str]]:
    """场景分类"""
    matched_keywords = []

    # 1. 强互斥关键词
    for signal, scenario in STRONG_SIGNALS.items():
        if signal in question:
            matched_keywords.append(signal)
            confidence = 0.85
            for kw in SCENARIO_KEYWORDS.get(scenario, []):
                if kw in question and kw != signal:
                    confidence = min(confidence + 0.05, 0.95)
                    matched_keywords.append(kw)
            return scenario, confidence, matched_keywords

    # 2. 常规匹配
    scores = {}
    for scenario, keywords in SCENARIO_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in question:
                score += 1
                matched_keywords.append(kw)
        scores[scenario] = score

    # 3. 组合规则
    for scenario, combos in COMBO_RULES.items():
        for kw1, kw2 in combos:
            if kw1 in question and kw2 in question:
                scores[scenario] = scores.get(scenario, 0) + 1.5
                matched_keywords.append(f"{kw1}+{kw2}")

    if not scores or max(scores.values()) == 0:
        return ScenarioType.UNKNOWN, 0.0, matched_keywords

    best_scenario = max(scores, key=scores.get)
    best_score = scores[best_scenario]
    confidence = min(0.5 + best_score * 0.1, 0.9)

    return best_scenario, confidence, list(set(matched_keywords))


def extract_districts(question: str) -> List[str]:
    """提取区县"""
    return [d for d in DISTRICT_KEYWORDS if d in question]


def has_gray_zone(question: str) -> bool:
    """是否涉及灰色地带
    付费层Step2前置过滤。只有纯概念解释类问题才跳过。
    """
    # 纯概念解释类问题关键词（这类问题不太涉及资格判断的灰色地带）
    pure_concept = ["是什么", "什么意思", "什么是", "怎么算", "定义"]
    # 如果问题纯是概念查询，且不涉及个人资格判断
    has_qualification_signal = any(kw in question for kw in [
        "我", "能不能", "行不行", "够不够", "可以吗", "符合",
        "社保", "户籍", "居住证", "随迁", "划片", "摇号",
    ])
    if has_qualification_signal:
        return True  # 涉及资格判断，总是触发
    # 纯概念问题：让LLM判断
    return True  # v2.0: 默认总是触发，由LLM判断是否有灰色地带


# 场景→wiki关键词映射（用于精准检索）
SCENARIO_WIKI_KEYWORDS = {
    ScenarioType.PRIMARY_TO_MIDDLE: ["小升初", "初中", "小学毕业", "摇号", "划片", "义务教育"],
    ScenarioType.KINDERGARTEN_TO_PRIMARY: ["幼升小", "小学入学", "幼儿园", "义务教育", "小学入学", "划片", "报名", "适龄儿童", "录取", "片区"],
    ScenarioType.TRANSFER: ["随迁", "居住证", "社保", "义务教育"],
    ScenarioType.MIDDLE_SCHOOL_EXAM: ["中考", "高中", "指标到校", "录取分数线", "录取", "分数", "普高线", "成都中考"],
    ScenarioType.DISTRICTING_COMPARISON: ["划片", "分片", "对口", "学区", "入学范围"],
}

# 场景→排除关键词（不应出现在参考来源中的）
SCENARIO_EXCLUDE_KEYWORDS = {
    ScenarioType.PRIMARY_TO_MIDDLE: ["幼儿园", "中考", "高中阶段"],
    ScenarioType.KINDERGARTEN_TO_PRIMARY: ["中考", "高中阶段", "初中"],
    ScenarioType.TRANSFER: ["中考", "高中阶段"],
    ScenarioType.MIDDLE_SCHOOL_EXAM: ["幼儿园", "幼升小"],
    ScenarioType.DISTRICTING_COMPARISON: ["中考", "高中"],
}


def collect_candidate_pages(scenario: ScenarioType, question: str) -> List[str]:
    """收集候选页面 — 场景精准匹配，绝不返回无关场景页面"""
    pages = []
    exclude_kws = SCENARIO_EXCLUDE_KEYWORDS.get(scenario, [])

    # 1. 核心政策页（始终包含）
    core_pages = CORE_POLICY_PAGES.get(scenario, [])
    for p in core_pages:
        if p not in pages:
            pages.append(p)

    # 2. 按场景关键词精准检索（非逐字检索）
    if wiki_loader.is_loaded():
        scenario_kws = SCENARIO_WIKI_KEYWORDS.get(scenario, [])
        for kw in scenario_kws:
            found = wiki_loader.list_pages_by_keyword(kw)
            for p in found:
                if p not in pages:
                    pages.append(p)

        # 3. 从问题中提取特定关键词检索（区县、学校名等）
        for d in extract_districts(question):
            found = wiki_loader.list_pages_by_keyword(d)
            for p in found:
                if p not in pages:
                    pages.append(p)

    # 4. 严格过滤：排除不属于当前场景的页面
    filtered = []
    for p in pages:
        excluded = False
        for ekw in exclude_kws:
            if ekw in p:
                excluded = True
                break
        if not excluded:
            filtered.append(p)

    # 排序：2026优先
    filtered.sort(key=lambda p: 0 if "2026" in p else (1 if "2025" in p else 2))

    return filtered[:10]  # 最多10页，减少噪声


# 前端学段参数 → 场景类型映射
STAGE_MAP = {
    "youshengxiao": ScenarioType.KINDERGARTEN_TO_PRIMARY,
    "xiaoshengchu": ScenarioType.PRIMARY_TO_MIDDLE,
    "suiqian": ScenarioType.TRANSFER,
    "zhongkao": ScenarioType.MIDDLE_SCHOOL_EXAM,
}


def route_question(question: str, stage: str = None) -> RouteResult:
    """路由问题 → 场景 + 候选页面

    Args:
        question: 用户问题
        stage: 前端传入的学段标识(xiaoshengchu/youshengxiao/suiqian/zhongkao)，
               优先级高于关键词匹配
    """
    # MVP: 如果前端明确传了学段，优先使用
    if stage:
        forced_scenario = STAGE_MAP.get(stage)
        if forced_scenario:
            # 仍然做关键词匹配获取matched_keywords，但场景以stage为准
            _, _, matched_keywords = classify_scenario(question)
            scenario = forced_scenario
            confidence = 0.85  # 用户自选学段，保底0.85置信度
        else:
            # stage参数不合法，fallback到关键词匹配
            scenario, confidence, matched_keywords = classify_scenario(question)
    else:
        scenario, confidence, matched_keywords = classify_scenario(question)

    candidate_pages = collect_candidate_pages(scenario, question)

    return RouteResult(
        scenario=scenario,
        confidence=confidence,
        matched_keywords=matched_keywords,
        candidate_pages=candidate_pages,
    )

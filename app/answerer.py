"""
四步裁决框架 v2.0 — 点灯蛙核心
Step1 情况理解 → Step2 灰色地带判断 → Step3 竞争烈度+路径推荐 → Step4 时间线+补救
免费层: Step1+基础8段输出 | 付费层: Step1-4完整输出
"""

import os
import json
import logging
import re
import httpx
from typing import List, Optional
from .models import (


    DiagnosisRequest, DiagnosisResult, ScenarioType,
    Step1SituationUnderstanding, Step2GrayZone,
    Step3CompetitionAndPaths, Step4Timeline, PathOption,
    CompetitionLevel, PlanType, FamilyInfo, AdvisorResult,
)
from .loaders import wiki_loader, gt_loader, lottery_loader, knowledge_card_loader
from .router import route_question, has_gray_zone, extract_districts
from app.url_extractor import extract_official_url_from_content

logger = logging.getLogger("k12_rocket")

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "45"))

# 禁止词
PROHIBITED_WORDS = [
    "保证录取", "包录取", "百分百录取", "100%录取",
    "走关系", "有关系", "内部关系",
    "内部指标", "内部渠道", "内部名额",
    "花钱买", "买学位", "买名额",
    "报我名字", "找我有路", "有门路",
    "疏通关系", "找关系入学",
]

# 黑话翻译表
JARGON_TABLE = {
    "大摇号": {
        "plain": "市级统筹的电脑随机录取，成都市教育局统一组织的6所名校摇号",
        "scenario": "小升初",
        "policy_ref": "2026年成都市义务教育招生入学政策",
    },
    "小摇号": {
        "plain": "区级统筹的电脑随机录取，按划片范围内摇号",
        "scenario": "小升初",
        "policy_ref": "各区义务教育招生入学实施细则",
    },
    "两个一致": {
        "plain": "户籍地与居住地一致、户籍与法定监护人一致——划片入学的核心条件",
        "scenario": "幼升小/小升初",
        "policy_ref": "成都市义务教育招生入学政策",
    },
    "DZ": {
        "plain": "定向招生——学校自主选拔，非公开渠道（注意：不鼓励，存在合规风险）",
        "scenario": "小升初",
        "policy_ref": "公民同招政策",
    },
    "QY": {
        "plain": "签约——学校与家长签入学意向协议",
        "scenario": "小升初/中考",
        "policy_ref": "各校自主招生政策",
    },
    "JX": {
        "plain": "均衡教育/就近入学——按居住地划片对口入学",
        "scenario": "幼升小/小升初",
        "policy_ref": "义务教育法",
    },
    "随迁": {
        "plain": "进城务工人员随迁子女——非本市户籍在成都申请入学的家庭",
        "scenario": "幼升小/小升初",
        "policy_ref": "成都市随迁子女入学政策",
    },
    "划片": {
        "plain": "按居住地划定的对口入学区域——你的住址决定你能上哪所公办学校",
        "scenario": "幼升小/小升初",
        "policy_ref": "各区划片范围公告",
    },
    "指标到校": {
        "plain": "省级示范性高中将部分招生名额分配到初中学校——校内竞争而非全区竞争",
        "scenario": "中考",
        "policy_ref": "成都市中考政策",
    },
    "公民同招": {
        "plain": "公办和民办学校同步招生——选择民办摇号即放弃公办划片资格（不可逆）",
        "scenario": "幼升小/小升初",
        "policy_ref": "2026年成都市义务教育招生入学政策",
    },
    "信息采集": {
        "plain": "入学信息网上登记——所有升学的第一步，必须按时完成",
        "scenario": "幼升小/小升初",
        "policy_ref": "成都市义务教育招生入学工作日程",
    },
    "多校划片": {
        "plain": "一个区域对口多所学校，通过摇号决定上哪所——不是你想去哪就去哪",
        "scenario": "小升初",
        "policy_ref": "各区小升初划片方案",
    },
}


def filter_prohibited(text: str) -> str:
    """过滤禁止词"""
    if not text:
        return text
    for word in PROHIBITED_WORDS:
        if word in text:
            text = text.replace(word, "⚠️[已过滤:涉嫌违规表述]")
    return text


def build_wiki_context(candidate_pages: List[str], max_chars: int = 12000) -> str:
    """构建Wiki知识上下文，2026优先"""
    context_parts = []
    total_chars = 0
    sorted_pages = sorted(candidate_pages, key=lambda p: 0 if "2026" in p else (1 if "2025" in p else 2))

    for page_path in sorted_pages:
        info = wiki_loader.get_page_info(page_path)
        content = wiki_loader.get_page_content(page_path)
        if info and content:
            title = info.get("title", page_path)
            source = info.get("source_grade", "")
            year = "2026" if "2026" in page_path else ("2025" if "2025" in page_path else "年份未标注")
            header = f"### {title} (数据年份: {year})\n" if not source else f"### [{source}] {title} (数据年份: {year})\n"
            max_page_chars = max_chars - total_chars - len(header)
            if max_page_chars < 200:
                break
            truncated = content[:max_page_chars]
            if len(content) > max_page_chars:
                truncated += "\n...(内容过长已截断)"
            context_parts.append(header + truncated)
            total_chars += len(header) + len(truncated)

    return "\n\n---\n\n".join(context_parts)



def build_knowledge_context(question, scenario="", max_chars=8000):
    """Build RAG context from dual-core knowledge base.

    Queries the KnowledgeCardLoader which reads JSON cards produced by
    opc_knowledge_builder.py from:
      - 0-golden-interpretations/ : Policy fact cards
      - 0-problems/ : Parent pain-point cards
    """
    if not knowledge_card_loader.is_loaded():
        return ""
    return knowledge_card_loader.get_context_text(
        question=question,
        scenario=scenario,
        max_chars=max_chars,
    )


# ============================================================
# Step1: 情况理解 — 规则引擎提取
# ============================================================

def step1_understand(question: str, route) -> Step1SituationUnderstanding:
    """从自然语言提取结构化家庭画像 — 增强容错版 v2.1"""
    family = FamilyInfo()
    districts = extract_districts(question)
    q = question  # shorthand

    # ── 户籍区县 ──────────────────────────────
    # 口语/书面: 户口在/户口/户籍/户籍地/户籍所在/户籍所在地/户藉/户口所在地/户口属于/户口挂靠/户口落在/落户/落户在/上户/上的户
    HOUSEHOLD_KWS = [
        "户口在", "户口", "户籍", "户籍地", "户籍所在", "户籍所在地",
        "户口所在地", "户口属于", "户口挂靠", "户口落在", "落户在", "落户",
        "上户", "上的户", "户在地", "户口迁", "户口迁入",
    ]
    # 居住区县口语: 住在/住/居住/租房/现居/现住/住在/生活/定居/租住在/暂住
    RESIDENCE_KWS = [
        "住在", "住", "居住", "租房", "现居", "现住", "生活", "定居",
        "租住在", "租住", "暂住", "租的房子", "租的房", "住的", "家在",
    ]
    # 社保区县口语: 社保/社保在/交社保/缴社保/社保交在/社保缴在/社保买在
    SOCIAL_SECURITY_KWS = [
        "社保", "社保在", "交社保", "缴社保", "社保交在", "社保缴在",
        "社保买在", "五险一金", "养老保",
    ]
    # 学籍区县口语: 学籍在/学籍/就读于/在读/就学
    SCHOOL_DISTRICT_KWS = [
        "学籍在", "学籍", "就读于", "就读", "在读", "就学",
    ]

    for d in districts:
        if any(kw in q for kw in HOUSEHOLD_KWS):
            if not family.household_district:
                family.household_district = d + "区"
        if any(kw in q for kw in RESIDENCE_KWS):
            if not family.residence_district:
                family.residence_district = d + "区"
        if any(kw in q for kw in SOCIAL_SECURITY_KWS):
            if not family.social_security_district:
                family.social_security_district = d + "区"
        # 学籍区县 → 如果还没有户籍区，优先填入
        if any(kw in q for kw in SCHOOL_DISTRICT_KWS):
            if not family.household_district:
                family.household_district = d + "区"
            if not family.residence_district:
                family.residence_district = d + "区"

    # Fallback: 只提到一个区且无关键词 → 默认为户籍区
    if districts and not family.household_district and not family.residence_district:
        family.household_district = districts[0] + "区"

    # ── 随迁判断 ──────────────────────────────
    TRANSFER_KWS = [
        "随迁", "随迁子女", "外来务工", "外来人员",
        "外省", "外地", "外市", "非本市", "非成都", "非成都户籍", "非本地",
        "流动人口", "进城务工", "外来人口", "异地",
        "户口不在成都", "户口不在本地", "外地户口", "外省户口",
        "不是成都人", "不是本地人", "老家不在成都",
        "外地来成都", "来成都打工", "来蓉务工", "来蓉",
    ]
    family.is_transfer = any(kw in q for kw in TRANSFER_KWS)

    # ── 居住证 ──────────────────────────────
    RESIDENCE_PERMIT_KWS = ["居住证", "暂住证", "居住登记"]
    if any(kw in q for kw in RESIDENCE_PERMIT_KWS):
        family.residence_permit = True
        m = re.search(r"(?:居住证|暂住证).*?(\d+)\s*个?月", q)
        if m:
            family.residence_permit_months = int(m.group(1))

    # ── 社保月数 ──────────────────────────────
    # 支持: "社保16个月" / "社保高新16个月" / "交了16个月社保" / "社保交了1年半"
    m = re.search(r"(?:社保|五险一金|养老保).*?(\d+)\s*个?月", q)
    if m:
        family.social_security_months = int(m.group(1))
    else:
        # "交了XX个月社保" / "社保交了XX个月"
        m = re.search(r"(?:交了|缴了|买了)\s*(\d+)\s*个?月\s*(?:社保|五险)", q)
        if m:
            family.social_security_months = int(m.group(1))
        else:
            # "X年X个月社保" → 换算
            m = re.search(r"(?:社保|五险).*?(\d+)\s*年(?:又|零|加|)?(\d+)\s*个?月", q)
            if m:
                family.social_security_months = int(m.group(1)) * 12 + int(m.group(2))

    # ── 孩子年龄 ──────────────────────────────
    # 主正则: 前缀+数字+岁
    AGE_PREFIX = r"(?:孩子|小孩|今年|年龄|岁数|娃|娃儿|宝宝|宝|儿|闺女|儿子|女儿|小朋友|今年已经|今年满|已经|满|今年\d+岁|小娃|宝贝|幺儿|小娃儿)"
    m = re.search(AGE_PREFIX + r".*?(\d+)\s*岁", q)
    if m and 3 <= int(m.group(1)) <= 18:
        family.child_age = int(m.group(1))
    else:
        # 反向: "XX岁的孩子/小孩/娃"
        m = re.search(r"(\d+)\s*岁\s*(?:的)?(?:孩子|小孩|娃|小朋友|宝宝|宝|儿|闺女|儿子|女儿|小娃|小娃儿)", q)
        if m and 3 <= int(m.group(1)) <= 18:
            family.child_age = int(m.group(1))
        else:
            # Fallback: 纯"XX岁" + 升学上下文
            enrollment_context = any(kw in q for kw in [
                "入学", "升学", "报名", "读书", "上学", "就读", "毕业",
                "小学", "初中", "高中", "幼升小", "小升初", "初升高", "中考",
                "摇号", "划片", "学位", "报名", "招生", "户籍", "户口",
                "随迁", "社保", "居住证", "学区", "对口",
            ])
            m = re.search(r"(\d+)\s*岁", q)
            if m and 3 <= int(m.group(1)) <= 18 and enrollment_context:
                family.child_age = int(m.group(1))

    # ── 学段/年级 ──────────────────────────────
    GRADE_MAP = {
        # 幼升小
        "幼儿园大班": "幼升小", "大班": "幼升小", "学前班": "幼升小",
        "幼升小": "幼升小", "幼儿园毕业": "幼升小", "上小学": "幼升小",
        "读小学": "小学", "小学入学": "幼升小",
        # 小学年级
        "一年级": "小学一年级", "二年级": "小学二年级", "三年级": "小学三年级",
        "四年级": "小学四年级", "五年级": "小学五年级", "六年级": "小学六年级",
        "小学": "小学",
        # 小升初
        "小升初": "小升初", "小学毕业": "小升初", "小学升初中": "小升初",
        "六年级毕业": "小升初", "马上初中": "小升初", "即将升初中": "小升初",
        "升初中": "小升初", "上初中": "小升初", "考初中": "小升初",
        # 初中年级
        "初一": "初一", "七年级": "初一", "初中一年级": "初一",
        "初二": "初二", "八年级": "初二", "初中二年级": "初二",
        "初三": "初三", "九年级": "初三", "初中三年级": "初三", "初中毕业": "初三",
        # 初升高/中考
        "初升高": "中考", "中考": "中考", "高中入学": "中考",
        "升高中": "中考", "考高中": "中考", "上高中": "中考",
        # 高中年级
        "高一": "高一", "高二": "高二", "高三": "高三",
    }
    for grade_kw, grade_val in GRADE_MAP.items():
        if grade_kw in q:
            family.child_grade = grade_val
            break

    # ── 区域推断增强 ──────────────────────────────
    if not family.residence_district and family.social_security_district:
        family.residence_district = family.social_security_district
    if not family.residence_district and not family.household_district and districts:
        family.residence_district = districts[0] + "区"

    # ── 目标学校 ──────────────────────────────
    known_schools = [
        "七中高新", "石室北湖", "树德光华", "树德外国语",
        "成都二中", "盐道街小学", "泡小", "实小", "龙江路",
        "成师附小", "胜西", "草小",
        "七中育才", "石室联中", "树德实验", "七中初中",
        "棕北中学", "川大附中", "铁中", "十二中", "列五中学",
        "华西中学", "玉林中学", "泡桐树", "天府七中",
    ]
    for s in known_schools:
        if s in q:
            family.target_schools.append(s)

    # ── 目标类型 ──────────────────────────────
    TARGET_TYPE_KWS = {
        "大摇号": ["大摇号", "市属摇号", "市级摇号", "大摇"],
        "划片": ["划片", "对口", "就近入学", "多校划片", "单校划片", "学区", "对口直升"],
        "民办": ["民办", "私立", "民校", "私立学校", "民办学校"],
        "随迁": ["随迁"],
    }
    for ttype, kws in TARGET_TYPE_KWS.items():
        if any(kw in q for kw in kws):
            family.target_type = ttype
            break
    if not family.target_type and family.is_transfer:
        family.target_type = "随迁"
    elif not family.target_type and "幼升小" in q:
        family.target_type = "划片"

    # ── 缺失信息 ──────────────────────────────
    missing = []
    if family.is_transfer:
        if not family.social_security_months:
            missing.append("社保连续缴纳月数")
        if not family.residence_permit:
            missing.append("是否有居住证")
        if not family.residence_district:
            missing.append("居住所在区县")
    if not family.household_district and not family.is_transfer:
        missing.append("户籍所在区县")
    if not family.child_age:
        missing.append("孩子年龄")

    # ── 概括 ──────────────────────────────
    parts = []
    if family.is_transfer:
        parts.append("随迁子女家庭")
    if family.household_district:
        parts.append(f"户籍{family.household_district}")
    if family.residence_district:
        parts.append(f"居住{family.residence_district}")
    if family.social_security_months:
        parts.append(f"社保{family.social_security_months}个月")
    if family.child_age:
        parts.append(f"孩子{family.child_age}岁")
    if family.child_grade:
        parts.append(f"{family.child_grade}")
    summary = "，".join(parts) if parts else "需要更多信息"

    return Step1SituationUnderstanding(
        family_profile=family,
        scenario=route.scenario,
        scenario_confidence=route.confidence,
        summary=summary,
        missing_info=missing,
    )


# ============================================================
# Step2: 灰色地带判断 — LLM生成
# ============================================================

STEP2_PROMPT = """你是一位成都升学政策专家。你的核心任务是找出用户情况中的"灰色地带"——即政策文本与实际执行之间存在温差的地方。

## ⛔ 严禁编造
- 绝不编造政策文号，只引用知识库中列出的真实政策标题
- 不确定的内容必须标注置信度

## ⚠️ 重要：灰色地带几乎总是存在的
成都升学政策存在大量灰色地带，几乎每个家庭的情况都涉及。不要轻易判断"无灰色地带"。
常见的灰色地带包括：
- 随迁子女：社保"连续缴纳"是累计还是连续？中断补缴算不算？各区审核松紧差异极大
- 社保时长：政策写6个月，但部分区实际查12个月才给学位（而非统筹）
- 居住证：有的区认电子证，有的要求实体证，过渡期新旧并存
- 划片：同一街道可能被划入不同学区，且每年微调
- 摇号：民办补录和空余计划的执行口径各区不同
- 材料："合法稳定住所"的证明材料各校要求宽严不一

只有当问题纯粹是概念解释（如"大摇号是什么"）且不涉及具体资格判断时，才可以输出"无灰色地带"。

## 对话上下文
{conversation_history}

## 用户问题
{question}

## 家庭画像
{family_summary}

## 相关政策内容
{wiki_context}

## 已验证的Ground Truth事实
{gt_context}

## 灰色地带类型
- 文字模糊：政策表述含糊，不同解读得出不同结论
- 执行差异：政策写的是一套，实际执行是另一套（如某些区查得严、某些区灵活）
- 区县差异：同一政策在不同区县执行口径不同
- 时效差异：政策过渡期，新旧政策衔接有模糊地带

## 输出格式（严格JSON，不要输出其他内容）
```json
{{
  "policy_text": "政策原文关键表述",
  "conservative_read": "保守版解释（严格按字面，对家长最不利）",
  "aggressive_read": "激进版解释（实际执行可能更灵活，对家长更有利）",
  "zone_type": "温差类型",
  "confidence": "置信度(🟢🟡🟠🔴)",
  "source": "信息来源"
}}
```

如果没有灰色地带（仅限纯概念解释类问题）：
```json
{{"policy_text": "", "conservative_read": "", "aggressive_read": "", "zone_type": "无灰色地带", "confidence": "🟢", "source": ""}}
```"""


# ============================================================
# Step3: 竞争烈度+路径推荐 — LLM生成
# ============================================================

STEP3_PROMPT = """你是一位成都升学路径规划专家。基于以下信息，为用户推荐升学路径组合。

## ⛔ 严禁编造
- 绝不编造数据，摇号率只使用下方历史数据
- 不确定的内容必须标注置信度

## 对话上下文
{conversation_history}

## 用户问题
{question}

## 家庭画像
{family_summary}

## 历史摇号数据
{lottery_data}

## 相关政策内容
{wiki_context}

## 已验证的Ground Truth事实
{gt_context}

## 竞争烈度等级
- 🔥🔥🔥🔥🔥 极度激烈：摇中率<3%，不建议作为唯一主战场
- 🔥🔥🔥🔥 激烈：摇中率3-8%，值得参与但不能指望
- 🔥🔥🔥 中等：摇中率8-20%，可作为冲刺位
- 🔥🔥 相对宽松：摇中率>20%，可以作为保底

## 重要提醒
- 2024年起官方不再汇总公布报名人数和中签率
- 竞争烈度基于历史数据评估，仅供参考
- 选择民办摇号=放弃公办划片资格（不可逆）

## 输出格式（严格JSON）
```json
{{
  "paths": [
    {{
      "path_name": "路径名称",
      "competition": "🔥🔥🔥🔥🔥",
      "competition_note": "竞争说明",
      "eligibility": "符合/可能符合/不符合",
      "eligibility_confidence": "🟢🟡🟠🔴",
      "key_requirement": "关键条件",
      "risk": "风险提示"
    }}
  ],
  "recommended_combo": "冲刺位+主战场+兜底 组合建议",
  "overall_assessment": "总体评估"
}}
```"""


# ============================================================
# Step4: 时间线+补救方案 — LLM生成
# ============================================================

STEP4_PROMPT = """你是一位成都升学时间规划专家。基于以下信息，为用户制定时间线和补救方案。

## ⛔ 严禁编造
- 绝不编造具体日期，只使用知识库中提到的时间节点
- 不确定的日期必须标注“以官方公告为准”

## 对话上下文
{conversation_history}

## 用户问题
{question}

## 家庭画像
{family_summary}

## 推荐路径
{path_summary}

## 相关政策内容（含时间节点）
{wiki_context}

## 输出格式（严格JSON）
```json
{{
  "action_items": [
    {{"deadline": "截止日期", "action": "需要做的事", "importance": "必须/建议/可选", "note": "备注"}}
  ],
  "fallback_plan": "如果主路径失败的补救/平替方案",
  "critical_deadline": "最近的关键截止日期"
}}
```"""


# ============================================================
# 统一8段输出Prompt（免费层+付费层基础）
# ============================================================

UNIVERSAL_PROMPT = """你是"点灯蛙"，一个专业的成都K12升学参谋。你的任务是根据家长的问题和提供的政策知识，生成结构化的8段评估报告。

## 🚨 政策年份优先级铁律
1. 凡是2026年已发布的政策，一律以2026年政策为准
2. 只有2026年尚未发布的内容，才可参考2025年数据，必须标注"参考2025年数据，以2026年官方后续公告为准"
3. 绝不允许将2025年政策当作最新政策引用

## 🛡️ 合规红线
1. 绝不暗示"走关系""内部渠道""内部指标"等违规途径
2. 绝不给"100%录取""保证录取"等绝对承诺
3. 所有建议必须基于官方公开政策，标注出处
4. 2024年后官方不再汇总公布中签率，绝不展示无来源摇中率

## ⛔ 严禁编造政策文号
1. 绝不编造"成招考委〔2026〕X号"之类的不实文号
2. 引用政策时只使用知识库中提供的真实政策标题
3. 如果不确定具体文号，只写政策标题即可，宁可不写文号也不能编造
4. 政策依据必须来自下方【知识库内容】中列出的具体文件，不要引用知识库中不存在的文件

## 💬 对话上下文
以下是之前对话的历史记录，请结合上下文理解用户问题，不要重复询问已经回答过的信息：
{conversation_history}

## 用户问题
{question}

## 家庭画像
{family_summary}

## 知识库内容
{wiki_context}

## 输出格式（严格JSON）
```json
{{
  "preliminary_conclusion": "1. 初步结论：1-3句话判断",
  "situation_type": "2. 情况分类：家庭属于哪种升学类型",
  "policy_basis": "3. 适用政策：只引用知识库中列出的政策标题，不编造文号",
  "key_timeline": "4. 关键时间节点：📅标注每个日期，按时间排序",
  "required_materials": "5. 需要准备的材料：分必需/可选",
  "risk_points": "6. 主要风险点：⚠️标注每条风险",
  "next_steps": "7. 下一步建议：冲刺/稳健/保底三层方案",
  "pending_questions": "8. 需确认问题：只需要真正缺失的关键信息，不要重复已知信息"
}}
```"""


# ============================================================
# LLM调用
# ============================================================

async def call_llm(system_prompt: str, user_prompt: str) -> str:
    """调用DeepSeek LLM"""
    if not DEEPSEEK_API_KEY:
        logger.warning("[LLM] API Key未配置，使用模板回退")
        return ""

    try:
        async with httpx.AsyncClient(timeout=float(DEEPSEEK_TIMEOUT)) as client:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 3000,
                },
            )
            data = resp.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0].get("message", {}).get("content", "")
            else:
                logger.error(f"[LLM] 响应异常: {data}")
                return ""
    except Exception as e:
        logger.error(f"[LLM] 调用失败: {e}")
        return ""


def parse_json_safely(text: str) -> dict:
    """安全解析LLM返回的JSON"""
    if not text:
        return {}
    # 提取```json ... ```中的内容
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result[0] if result and isinstance(result[0], dict) else {}
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        # 尝试修复常见问题
        text = text.replace('\n', '\\n').replace('\t', '\\t')
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result[0] if result and isinstance(result[0], dict) else {}
            return result if isinstance(result, dict) else {}
        except:
            return {}


# ============================================================
# 主入口：四步裁决引擎
# ============================================================

async def generate_diagnosis(request: DiagnosisRequest, route) -> DiagnosisResult:
    """四步裁决引擎主入口"""

    question = request.question
    plan = request.plan or PlanType.FREE
    conversation_history = request.conversation_history or []

    # 收集wiki上下文
    wiki_context = build_wiki_context(route.candidate_pages)

    # Build dual-core knowledge context (golden interpretations + pain points)
    knowledge_context = build_knowledge_context(
        question=question,
        scenario=route.scenario.value if route.scenario else "",
    )

    # Merge knowledge_context into wiki_context for LLM prompts
    combined_context = wiki_context
    if knowledge_context:
        combined_context = wiki_context + "\n\n---\n\n## Dual-Core Knowledge Base\n\n" + knowledge_context

    # GT校准（第一轮：仅基于问题）
    gt_results = []
    if gt_loader.is_loaded():
        gt_result = gt_loader.validate(question, route.scenario.value if route.scenario else "")
        if gt_result.get("verified") is not None:
            gt_results.append(gt_result)

    # ---- Step1: 情况理解（所有用户） ----
    step1 = step1_understand(question, route)
    
    # 如果有对话历史，尝试从历史中补充家庭画像缺失信息
    if conversation_history:
        for msg in conversation_history:
            if msg.get("role") == "user":
                hist_text = msg.get("content", "")
                # 补充随迁标志
                if not step1.family_profile.is_transfer:
                    transfer_kws = ["随迁", "随迁子女", "外省", "外地", "外市", "非本市", "非成都", "非成都户籍", "非本地", "流动人口", "进城务工", "外来务工", "外来人员", "外地户口", "外省户口", "户口不在成都", "户口不在本地", "不是成都人", "不是本地人", "暂住", "来蓉务工"]
                    if any(kw in hist_text for kw in transfer_kws):
                        step1.family_profile.is_transfer = True
                        if not step1.family_profile.target_type:
                            step1.family_profile.target_type = "随迁"
                # 补充社保月数
                if not step1.family_profile.social_security_months:
                    m = re.search(r"社保.*?(\d+)\s*个?月", hist_text)
                    if m:
                        step1.family_profile.social_security_months = int(m.group(1))
                # 补充区县信息
                hist_districts = extract_districts(hist_text)
                for d in hist_districts:
                    if any(kw in hist_text for kw in ["户籍", "户口", "户籍地", "户籍所在", "落户", "户口所在", "户口属于", "户口落在", "户口迁"]):
                        if not step1.family_profile.household_district:
                            step1.family_profile.household_district = d + "区"
                    if any(kw in hist_text for kw in ["住", "居住", "租房", "现居", "现住", "租住", "暂住", "生活", "定居", "家在"]):
                        if not step1.family_profile.residence_district:
                            step1.family_profile.residence_district = d + "区"
                    if any(kw in hist_text for kw in ["社保", "交社保", "缴社保", "五险一金"]):
                        if not step1.family_profile.social_security_district:
                            step1.family_profile.social_security_district = d + "区"
                # 补充年龄
                if not step1.family_profile.child_age:
                    m = re.search(r"(?:孩子|小孩|今年|年龄|岁数|娃|娃儿|宝宝|宝|儿|闺女|儿子|女儿|小朋友|今年已经|今年满|已经|满|幺儿).*?(\d+)\s*岁", hist_text)
                    if m:
                        step1.family_profile.child_age = int(m.group(1))
                # 补充居住证
                if "居住证" in hist_text and not step1.family_profile.residence_permit:
                    step1.family_profile.residence_permit = True
                    m = re.search(r"居住证.*?(\d+)\s*个?月", hist_text)
                    if m:
                        step1.family_profile.residence_permit_months = int(m.group(1))
                # 补充学段
                if not step1.family_profile.child_grade:
                    GRADE_MAP_HIST = {
                        "幼儿园大班": "幼升小", "大班": "幼升小", "幼升小": "幼升小",
                        "小升初": "小升初", "小学毕业": "小升初", "升初中": "小升初", "上初中": "小升初",
                        "初升高": "中考", "中考": "中考", "升高中": "中考", "上高中": "中考",
                        "初一": "初一", "初二": "初二", "初三": "初三",
                        "高一": "高一", "高二": "高二", "高三": "高三",
                    }
                    for gk, gv in GRADE_MAP_HIST.items():
                        if gk in hist_text:
                            step1.family_profile.child_grade = gv
                            break

                # 如果社保区已设置但居住区未设置，推断居住区=社保区
        if not step1.family_profile.residence_district and step1.family_profile.social_security_district:
            step1.family_profile.residence_district = step1.family_profile.social_security_district
        # 重新生成summary
        parts = []
        if step1.family_profile.is_transfer:
            parts.append("随迁子女家庭")
        if step1.family_profile.household_district:
            parts.append(f"户籍{step1.family_profile.household_district}")
        if step1.family_profile.residence_district:
            parts.append(f"居住{step1.family_profile.residence_district}")
        if step1.family_profile.social_security_months:
            parts.append(f"社保{step1.family_profile.social_security_months}个月")
        if step1.family_profile.child_age:
            parts.append(f"孩子{step1.family_profile.child_age}岁")
        if step1.family_profile.child_grade:
            parts.append(f"{step1.family_profile.child_grade}")
        step1.summary = "，".join(parts) if parts else "需要更多信息"
        # 重新计算缺失信息
        missing = []
        if step1.family_profile.is_transfer:
            if not step1.family_profile.social_security_months:
                missing.append("社保连续缴纳月数")
            if not step1.family_profile.residence_permit:
                missing.append("是否有居住证")
            if not step1.family_profile.residence_district:
                missing.append("居住所在区县")
        if not step1.family_profile.household_district and not step1.family_profile.is_transfer:
            missing.append("户籍所在区县")
        if not step1.family_profile.child_age:
            missing.append("孩子年龄")
        step1.missing_info = missing
    
    family_summary = step1.summary

    # GT校准（第二轮：基于家庭画像补充校准）
    if gt_loader.is_loaded():
        if step1.family_profile.is_transfer:
            gt2 = gt_loader.validate("随迁子女社保", "随迁子女")
            if gt2.get("verified") and gt2 not in gt_results:
                gt_results.append(gt2)

    # 构建GT校准文本注入付费层prompt
    gt_context = ""
    if gt_results:
        gt_parts = []
        for g in gt_results:
            part = f"已验证事实：{g.get('fact', '')}"
            if g.get('common_error'):
                part += f"\n常见错误：{g['common_error']}"
            if g.get('correction'):
                part += f"\n正确说法：{g['correction']}"
            part += f"\n置信度：{g.get('confidence', '🟡')}"
            gt_parts.append(part)
        gt_context = "\n\n".join(gt_parts)

    # 构建对话历史文本
    history_text = ""
    if conversation_history:
        history_lines = []
        for msg in conversation_history[-10:]:  # 最近10轮
            role = "用户" if msg.get("role") == "user" else "助手"
            history_lines.append(f"{role}: {msg.get('content', '')}")
        history_text = "\n".join(history_lines)
    else:
        history_text = "（这是本轮对话的第一条消息）"

    # ---- 8段基础输出（所有用户，LLM生成） ----
    universal_prompt = UNIVERSAL_PROMPT.format(
        question=question,
        family_summary=family_summary,
        wiki_context=combined_context[:10000],
        conversation_history=history_text,
    )

    llm_output = await call_llm("你是成都K12升学参谋点灯蛙。", universal_prompt)
    base_result = parse_json_safely(llm_output)

    # 应用禁止词过滤
    for key in base_result:
        if isinstance(base_result[key], str):
            base_result[key] = filter_prohibited(base_result[key])

    # 构建基础结果
    result = DiagnosisResult(
        question=question,
        scenario=route.scenario,
        preliminary_conclusion=base_result.get("preliminary_conclusion", ""),
        situation_type=base_result.get("situation_type", step1.summary),
        policy_basis=base_result.get("policy_basis", ""),
        key_timeline=base_result.get("key_timeline", ""),
        required_materials=base_result.get("required_materials", ""),
        risk_points=base_result.get("risk_points", ""),
        next_steps=base_result.get("next_steps", ""),
        pending_questions=base_result.get("pending_questions", ""),
        step1=step1,
        confidence=route.confidence,
        plan_used=plan,
    )

    # 添加引用
    for page_path in route.candidate_pages[:5]:
        info = wiki_loader.get_page_info(page_path)
        content = wiki_loader.get_page_content(page_path)
        if info:
            result.references.append({
                "path": page_path,
                "title": info.get("title", ""),
                "source_grade": info.get("source_grade", ""),
                "excerpt": (content[:200] if content else "")[:200],
                "official_url": extract_official_url_from_content(content, info.get("title", "")),
            })

    # ---- 付费层独占：Step2-4 ----
    if plan in (PlanType.LITE, PlanType.MAX):
        import asyncio as _asyncio

        async def dummy_task():
            return ""

        tasks = []
        run_step2 = has_gray_zone(question)

        # 1. Step2: 灰色地带任务
        if run_step2:
            step2_prompt = STEP2_PROMPT.format(
                question=question,
                family_summary=family_summary,
                wiki_context=combined_context[:6000],
                conversation_history=history_text,
                gt_context=gt_context,
            )
            tasks.append(call_llm("你是成都升学政策灰色地带分析专家。", step2_prompt))
        else:
            tasks.append(dummy_task())

        # 2. Step3: 竞争与路径推荐任务
        lottery_data = "暂无历史摇号数据"
        if lottery_loader.is_loaded() and lottery_loader.data:
            lottery_data = json.dumps(lottery_loader.data[-10:], ensure_ascii=False, indent=2)

        step3_prompt = STEP3_PROMPT.format(
            question=question,
            family_summary=family_summary,
            lottery_data=lottery_data,
            wiki_context=combined_context[:6000],
            conversation_history=history_text,
            gt_context=gt_context,
        )
        tasks.append(call_llm("你是成都升学路径规划专家。", step3_prompt))

        # 3. Step4: 时间线规划任务
        step4_prompt = STEP4_PROMPT.format(
            question=question,
            family_summary=family_summary,
            path_summary=family_summary,  # 先用family_summary，Step3结果未出
            wiki_context=combined_context[:6000],
            conversation_history=history_text,
        )
        tasks.append(call_llm("你是成都升学时间规划专家。", step4_prompt))

        # 并行执行 Step 2, 3, 4 的 LLM 调用
        outputs = await _asyncio.gather(*tasks)

        # 解析 Step2
        if run_step2 and outputs[0]:
            step2_data = parse_json_safely(outputs[0])
            if step2_data and isinstance(step2_data, dict) and step2_data.get("zone_type") != "无灰色地带":
                result.step2 = Step2GrayZone(
                    policy_text=step2_data.get("policy_text", ""),
                    conservative_read=step2_data.get("conservative_read", ""),
                    aggressive_read=step2_data.get("aggressive_read", ""),
                    zone_type=step2_data.get("zone_type", ""),
                    confidence=step2_data.get("confidence", "🟡"),
                    source=step2_data.get("source", ""),
                )

        # 解析 Step3
        step3_output = outputs[1]
        step3_data = parse_json_safely(step3_output)
        if step3_data and isinstance(step3_data, dict):
            paths = []
            for p in step3_data.get("paths", []):
                comp = p.get("competition", "🔥🔥🔥")
                try:
                    comp_enum = CompetitionLevel(comp)
                except ValueError:
                    comp_enum = CompetitionLevel.MODERATE
                paths.append(PathOption(
                    path_name=p.get("path_name", ""),
                    competition=comp_enum,
                    competition_note=p.get("competition_note", ""),
                    eligibility=p.get("eligibility", ""),
                    eligibility_confidence=p.get("eligibility_confidence", "🟡"),
                    key_requirement=p.get("key_requirement", ""),
                    risk=p.get("risk", ""),
                ))
            result.step3 = Step3CompetitionAndPaths(
                paths=paths,
                recommended_combo=step3_data.get("recommended_combo", ""),
                overall_assessment=step3_data.get("overall_assessment", ""),
            )

        # 解析 Step4
        step4_output = outputs[2]
        step4_data = parse_json_safely(step4_output)
        if step4_data and isinstance(step4_data, dict):
            result.step4 = Step4Timeline(
                action_items=step4_data.get("action_items", []),
                fallback_plan=step4_data.get("fallback_plan", ""),
                critical_deadline=step4_data.get("critical_deadline", ""),
            )

    return result


def translate_jargon(term: str) -> dict:
    """黑话翻译"""
    result = JARGON_TABLE.get(term)
    if result:
        return {
            "term": term,
            "plain": result["plain"],
            "scenario": result["scenario"],
            "policy_ref": result["policy_ref"],
        }
    # 模糊匹配
    for key, val in JARGON_TABLE.items():
        if term in key or key in term:
            return {
                "term": key,
                "plain": val["plain"],
                "scenario": val["scenario"],
                "policy_ref": val["policy_ref"],
            }
    return {"term": term, "plain": "暂未收录此术语", "scenario": "", "policy_ref": ""}

"""

K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋

数据模型定义：四步裁决引擎 + 配额系统 + 用户画像

"""



from pydantic import BaseModel, Field

from typing import List, Optional, Dict

from enum import Enum

from datetime import datetime





# ============================================================

# 场景类型

# ============================================================



class ScenarioType(str, Enum):

    KINDERGARTEN_TO_PRIMARY = "幼升小"

    PRIMARY_TO_MIDDLE = "小升初"

    TRANSFER = "随迁子女"

    MIDDLE_SCHOOL_EXAM = "中考"

    UNKNOWN = "未知"





# ============================================================

# 用户画像（家庭信息结构化）

# ============================================================



class FamilyInfo(BaseModel):

    """家庭画像 — 四步裁决引擎Step1的输出"""

    # 基础

    household_district: str = Field("", description="户籍所在区县")

    residence_district: str = Field("", description="居住所在区县")

    child_age: Optional[int] = Field(None, description="孩子年龄")

    child_grade: str = Field("", description="当前学段")



    # 随迁相关

    is_transfer: bool = Field(False, description="是否随迁子女")

    social_security_district: str = Field("", description="社保缴纳区县")

    social_security_months: Optional[int] = Field(None, description="社保连续月数")

    residence_permit: bool = Field(False, description="是否有居住证")

    residence_permit_months: Optional[int] = Field(None, description="居住证持有时长(月)")



    # 目标

    target_schools: List[str] = Field(default_factory=list, description="意向学校")

    target_type: str = Field("", description="目标类型: 划片/大摇号/民办/随迁")



    # 软变量

    special_notes: str = Field("", description="特殊情况说明")





# ============================================================

# 配额系统

# ============================================================



class PlanType(str, Enum):

    FREE = "free"

    LITE = "lite"

    MAX = "max"





class QuotaInfo(BaseModel):

    """用户配额状态"""

    plan: PlanType = PlanType.FREE

    # 免费层：每周5次查询

    weekly_queries_used: int = 0

    weekly_queries_reset: str = Field("", description="本周重置日期")

    # Pro Lite：每月3次深度诊断

    monthly_diagnoses_used: int = 0

    monthly_diagnoses_reset: str = Field("", description="本月重置日期")

    # One-shot 报告

    reports_remaining: int = 0





class UserRecord(BaseModel):

    """用户记录 — data/users.json 的条目"""

    openid: str = ""

    nickname: str = ""

    plan: PlanType = PlanType.FREE

    quota: QuotaInfo = Field(default_factory=QuotaInfo)

    family_info: FamilyInfo = Field(default_factory=FamilyInfo)

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    last_active: str = Field(default_factory=lambda: datetime.now().isoformat())





# ============================================================

# 四步裁决引擎数据模型

# ============================================================



class Step1SituationUnderstanding(BaseModel):

    """Step1: 情况理解 — 自然语言→结构化家庭画像"""

    family_profile: FamilyInfo = Field(default_factory=FamilyInfo)

    scenario: ScenarioType = ScenarioType.UNKNOWN

    scenario_confidence: float = Field(0.0, ge=0, le=1)

    summary: str = Field("", description="一句话概括家庭情况")

    missing_info: List[str] = Field(default_factory=list, description="还缺什么信息")





class Step2GrayZone(BaseModel):

    """Step2: 灰色地带判断 — 政策文本vs实际执行温差"""

    policy_text: str = Field("", description="政策原文表述")

    conservative_read: str = Field("", description="保守版解释（严格字面）")

    aggressive_read: str = Field("", description="激进版解释（实际执行更灵活）")

    zone_type: str = Field("", description="温差类型: 文字模糊/执行差异/区县差异/时效差异")

    confidence: str = Field("🟡", description="置信度: 🟢🟡🟠🔴")

    source: str = Field("", description="信息来源")





class CompetitionLevel(str, Enum):

    EXTREME = "🔥🔥🔥🔥🔥"

    HIGH = "🔥🔥🔥🔥"

    MODERATE = "🔥🔥🔥"

    LOW = "🔥🔥"





class PathOption(BaseModel):

    """单条升学路径"""

    path_name: str = Field("", description="路径名称")

    competition: CompetitionLevel = CompetitionLevel.MODERATE

    competition_note: str = Field("", description="竞争说明")

    eligibility: str = Field("", description="资格判断: 符合/可能符合/不符合")

    eligibility_confidence: str = Field("🟡")

    key_requirement: str = Field("", description="关键条件")

    risk: str = Field("", description="风险提示")





class Step3CompetitionAndPaths(BaseModel):

    """Step3: 竞争烈度评估+路径推荐"""

    paths: List[PathOption] = Field(default_factory=list)

    recommended_combo: str = Field("", description="推荐组合: 冲刺位+主战场+兜底")

    overall_assessment: str = Field("", description="总体评估")





class Step4Timeline(BaseModel):

    """Step4: 时间线规划+补救方案"""

    action_items: List[Dict] = Field(default_factory=list, description="带截止日期的行动清单")

    fallback_plan: str = Field("", description="补救/平替方案")

    critical_deadline: str = Field("", description="最近关键截止日")





class AdvisorResult(BaseModel):

    """四步裁决完整输出"""

    question: str = ""

    step1: Step1SituationUnderstanding = Field(default_factory=Step1SituationUnderstanding)

    step2: Optional[Step2GrayZone] = None

    step3: Optional[Step3CompetitionAndPaths] = None

    step4: Optional[Step4Timeline] = None

    # 兼容v1前端

    preliminary_conclusion: str = ""

    situation_type: str = ""

    policy_basis: str = ""

    key_timeline: str = ""

    required_materials: str = ""

    risk_points: str = ""

    next_steps: str = ""

    pending_questions: str = ""

    # 元信息

    references: List[Dict] = Field(default_factory=list)

    confidence: float = 0.5

    plan_used: PlanType = PlanType.FREE





# ============================================================

# API请求/响应

# ============================================================



class DiagnosisRequest(BaseModel):

    """诊断请求 — 兼容v1"""

    question: str = Field(..., description="用户问题")

    user_type: Optional[str] = Field(None, description="用户类型")

    district: Optional[str] = Field(None, description="区县")

    child_age: Optional[int] = Field(None, description="孩子年龄")

    current_stage: Optional[str] = Field(None, description="学段")

    # v2新增

    openid: str = Field("", description="微信openid（用于配额）")

    plan: PlanType = PlanType.FREE

    conversation_history: Optional[List[Dict]] = Field(None, description="对话历史[{role,content}]")





class DiagnosisResult(BaseModel):

    """诊断结果 — v1兼容 + v2四步引擎"""

    question: str = ""

    scenario: ScenarioType = ScenarioType.UNKNOWN

    # v1 8段输出（保留兼容）

    preliminary_conclusion: str = ""

    situation_type: str = ""

    policy_basis: str = ""

    key_timeline: str = ""

    required_materials: str = ""

    risk_points: str = ""

    next_steps: str = ""

    pending_questions: str = ""

    # v2 四步引擎

    step1: Optional[Step1SituationUnderstanding] = None

    step2: Optional[Step2GrayZone] = None

    step3: Optional[Step3CompetitionAndPaths] = None

    step4: Optional[Step4Timeline] = None

    # 元信息

    references: List[Dict] = Field(default_factory=list)

    evidence_sufficient: bool = True

    confidence: float = 0.5

    plan_used: PlanType = PlanType.FREE





class FeedbackRequest(BaseModel):

    """用户反馈"""

    question: str = ""

    scenario: str = ""

    feedback_type: str = Field(..., description="accurate/inaccurate")

    correction: str = ""

    timestamp: str = ""





class RouteResult(BaseModel):

    """路由结果"""

    scenario: ScenarioType = ScenarioType.UNKNOWN

    confidence: float = 0.0

    matched_keywords: list = Field(default_factory=list)

    candidate_pages: list = Field(default_factory=list)





class HealthResponse(BaseModel):

    """健康检查"""

    status: str = "ok"

    version: str = "2.0.0"

    wiki_pages_count: int = 0

    index_loaded: bool = False

    engine: str = "advisor-v2"





class JargonRequest(BaseModel):

    """黑话翻译请求"""

    term: str = Field(..., description="要翻译的黑话")





class JargonResult(BaseModel):

    """黑话翻译结果"""

    term: str = ""

    plain: str = Field("", description="白话解释")

    scenario: str = Field("", description="使用场景")

    policy_ref: str = Field("", description="政策依据")


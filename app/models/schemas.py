"""
K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋

数据模型定义：四步裁决引擎 + 配额系统 + 用户画像 + 付费模式
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from enum import Enum
from datetime import datetime
import uuid


# ============================================================
# 场景类型
# ============================================================

class ScenarioType(str, Enum):
    KINDERGARTEN_TO_PRIMARY = "幼升小"
    PRIMARY_TO_MIDDLE = "小升初"
    TRANSFER = "随迁子女"
    MIDDLE_SCHOOL_EXAM = "中考"
    DISTRICTING_COMPARISON = "districting_comparison"
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


class FamilyProfile(BaseModel):
    """家庭画像扩展模型 — 包含按次诊断计费字段"""
    # 基础信息
    openid: str = ""
    nickname: str = ""
    plan: PlanType = PlanType.FREE
    quota: QuotaInfo = Field(default_factory=QuotaInfo)
    family_info: FamilyInfo = Field(default_factory=FamilyInfo)
    
    # 按次诊断计费：剩余诊断次数（默认0）
    diagnosis_credits: int = Field(0, description="按次诊断剩余次数")
    
    # 月度免费查询使用情况
    monthly_free_queries_used: int = Field(0, description="当月已用免费查询次数")
    
    # 时间戳
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_active: str = Field(default_factory=lambda: datetime.now().isoformat())


class UserRecord(BaseModel):
    """用户记录 — data/users.json 的条目"""
    openid: str = ""
    nickname: str = ""
    plan: PlanType = PlanType.FREE
    quota: QuotaInfo = Field(default_factory=QuotaInfo)
    family_info: FamilyInfo = Field(default_factory=FamilyInfo)
    # 按次诊断计费：剩余诊断次数（默认0）
    diagnosis_credits: int = Field(0, description="按次诊断剩余次数")
    monthly_free_queries_used: int = Field(0, description="当月已用免费查询次数")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_active: str = Field(default_factory=lambda: datetime.now().isoformat())


# ============================================================
# 付费记录模型
# ============================================================

class PaymentStatus(str, Enum):
    """支付状态枚举"""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class PaymentRecord(BaseModel):
    """支付记录 — 按次诊断计费"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="支付记录唯一ID")
    user_id: str = Field("", description="用户openid")
    order_no: str = Field("", description="订单号（业务唯一）")
    amount: float = Field(0.0, description="支付金额（元）")
    credits: int = Field(0, description="购买诊断次数")
    status: PaymentStatus = Field(PaymentStatus.PENDING, description="支付状态")
    payment_method: str = Field("", description="支付方式：wechat/alipay")
    transaction_id: str = Field("", description="微信/支付宝交易号")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="创建时间")
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="更新时间")
    paid_at: Optional[str] = Field(None, description="支付完成时间")
    refunded_at: Optional[str] = Field(None, description="退款时间")
    remark: str = Field("", description="备注信息")


class PaymentRequest(BaseModel):
    """支付请求参数"""
    user_id: str = Field(..., description="用户openid")
    credits: int = Field(..., ge=1, description="购买诊断次数（至少1次）")
    payment_method: str = Field("wechat", description="支付方式：wechat/alipay")
    remark: str = Field("", description="备注信息")


class PaymentResponse(BaseModel):
    """支付响应"""
    success: bool = Field(False, description="是否成功")
    message: str = Field("", description="提示信息")
    payment_record: Optional[PaymentRecord] = Field(None, description="支付记录")
    prepay_id: Optional[str] = Field(None, description="微信预支付ID")
    order_no: Optional[str] = Field(None, description="订单号")


class DiagnosisUsageRecord(BaseModel):
    """诊断使用记录"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="使用记录唯一ID")
    user_id: str = Field("", description="用户openid")
    diagnosis_type: str = Field("", description="诊断类型：school_match/transfer_analysis/etc")
    credits_used: int = Field(1, description="消耗诊断次数")
    result_summary: str = Field("", description="诊断结果摘要")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="使用时间")
    payment_record_id: Optional[str] = Field(None, description="关联支付记录ID")


class CreditPackage(BaseModel):
    """诊断次数套餐"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="套餐唯一ID")
    name: str = Field("", description="套餐名称")
    credits: int = Field(0, description="诊断次数")
    price: float = Field(0.0, description="价格（元）")
    original_price: float = Field(0.0, description="原价（元）")
    is_active: bool = Field(True, description="是否启用")
    description: str = Field("", description="套餐描述")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="创建时间")


# ============================================================
# 付费配置
# ============================================================

class PaymentConfig(BaseModel):
    """支付配置"""
    # 微信支付配置
    wechat_app_id: str = Field("", description="微信小程序AppID")
    wechat_mch_id: str = Field("", description="微信商户号")
    wechat_api_key: str = Field("", description="微信支付API密钥")
    wechat_cert_path: str = Field("", description="微信证书路径")
    wechat_notify_url: str = Field("", description="微信支付回调URL")
    
    # 支付宝配置
    alipay_app_id: str = Field("", description="支付宝AppID")
    alipay_private_key: str = Field("", description="支付宝私钥")
    alipay_public_key: str = Field("", description="支付宝公钥")
    alipay_notify_url: str = Field("", description="支付宝回调URL")
    
    # 诊断次数价格配置
    credit_price_per_unit: float = Field(9.9, description="单次诊断价格（元）")
    credit_packages: List[CreditPackage] = Field(default_factory=list, description="诊断套餐列表")
    
    # 免费额度配置
    free_daily_queries: int = Field(5, description="每日免费查询次数")
    free_monthly_diagnoses: int = Field(3, description="每月免费诊断次数")
    
    # 过期配置
    credit_expire_days: int = Field(365, description="诊断次数有效期（天）")

# ============================================================
# Missing Schemas (Restored)
# ============================================================

class Step1SituationUnderstanding(BaseModel):
    family_profile: FamilyInfo = Field(default_factory=FamilyInfo)
    scenario: ScenarioType = ScenarioType.UNKNOWN
    scenario_confidence: float = Field(0.0, ge=0, le=1)
    summary: str = Field("", description="一句话家庭描述")
    missing_info: List[str] = Field(default_factory=list, description="还缺什么信息")

class Step2GrayZone(BaseModel):
    policy_text: str = Field("", description="政策原文")
    conservative_read: str = Field("", description="保守解读（合规底线）")
    aggressive_read: str = Field("", description="积极解读（实际执行弹性）")
    zone_type: str = Field("", description="灰色地带类型: 模糊/执行差异/特批/时效性")
    confidence: str = Field("", description="确定度")
    source: str = Field("", description="信息来源")

class CompetitionLevel(str, Enum):
    EXTREME = "extreme"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"

class PathOption(BaseModel):
    path_name: str = Field("", description="升学路径名称")
    competition: CompetitionLevel = CompetitionLevel.MODERATE
    competition_note: str = Field("", description="竞争烈度说明")
    eligibility: str = Field("", description="资格判定: 稳/大概率/冲")
    eligibility_confidence: str = Field("")
    key_requirement: str = Field("", description="关键要求")
    risk: str = Field("", description="风险提示")

class Step3CompetitionAndPaths(BaseModel):
    paths: List[PathOption] = Field(default_factory=list)
    recommended_combo: str = Field("", description="推荐组合: 主力路径+兜底+备选")
    overall_assessment: str = Field("", description="综合评估")

class Step4Timeline(BaseModel):
    action_items: List[Dict] = Field(default_factory=list, description="实操节点行动清单")
    fallback_plan: str = Field("", description="兜底/平替方案")
    critical_deadline: str = Field("", description="关键截止日期")

class AdvisorResult(BaseModel):
    question: str = ""
    step1: Step1SituationUnderstanding = Field(default_factory=Step1SituationUnderstanding)
    step2: Optional[Step2GrayZone] = None
    step3: Optional[Step3CompetitionAndPaths] = None
    step4: Optional[Step4Timeline] = None
    preliminary_conclusion: str = ""
    situation_type: str = ""
    policy_basis: str = ""
    key_timeline: str = ""
    required_materials: str = ""
    risk_points: str = ""
    next_steps: str = ""
    pending_questions: str = ""
    references: List[Dict] = Field(default_factory=list)
    confidence: float = 0.5
    plan_used: PlanType = PlanType.FREE

class DiagnosisRequest(BaseModel):
    question: str = Field(..., description="用户问题")
    user_type: Optional[str] = Field(None, description="用户类型")
    district: Optional[str] = Field(None, description="地区")
    child_age: Optional[int] = Field(None, description="孩子年龄")
    current_stage: Optional[str] = Field(None, description="当前学段")
    openid: str = Field("", description="微信openid（可选）")
    plan: PlanType = PlanType.FREE
    conversation_history: Optional[List[Dict]] = Field(None, description="对话历史[{role,content}]")
    stage: Optional[str] = Field(None, description="用户选定的升学学段: xiaoshengchu/youshengxiao/suiqian/zhongkao")

class DiagnosisResult(BaseModel):
    request: DiagnosisRequest = Field(default_factory=DiagnosisRequest, description="原始请求")
    result: Dict = Field(default_factory=dict, description="诊断结果")
    credits_used: int = Field(0, description="消耗点数")
    credits_remaining: int = Field(0, description="剩余点数")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="创建时间")

class FeedbackRequest(BaseModel):
    question: str = ""
    scenario: str = ""
    feedback_type: str = Field(..., description="accurate/inaccurate")
    correction: str = ""
    timestamp: str = ""

class RouteResult(BaseModel):
    scenario: ScenarioType = ScenarioType.UNKNOWN
    confidence: float = 0.0

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "2.0.0"
    wiki_pages_count: int = 0
    index_loaded: bool = False
    engine: str = "advisor-v2"

class JargonRequest(BaseModel):
    term: str = Field(..., description="要翻译的行话")

class JargonResult(BaseModel):
    term: str = ""
    plain: str = Field("", description="白话")
    scenario: str = Field("", description="使用场景")
    policy_ref: str = Field("", description="政策依据")

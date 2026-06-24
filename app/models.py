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
    credits: int = Field(0, description="购买的诊断次数")
    status: PaymentStatus = PaymentStatus.PENDING
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="创建时间")
    paid_at: Optional[str] = Field(None, description="支付完成时间")
    # 微信支付相关字段
    prepay_id: Optional[str] = Field(None, description="微信预支付ID")
    transaction_id: Optional[str] = Field(None, description="微信支付订单号")
    # 商品描述
    description: str = Field("", description="商品描述")
    # 附加信息
    extra: Dict = Field(default_factory=dict, description="附加信息")
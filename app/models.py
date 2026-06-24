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


# ============================================================
# 诊断记录模型
# ============================================================

class DiagnosisRecord(BaseModel):
    """诊断记录 — 记录每次诊断的详细信息"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="诊断记录唯一ID")
    user_id: str = Field("", description="用户openid")
    scenario: ScenarioType = ScenarioType.UNKNOWN
    # 诊断输入
    family_info: FamilyInfo = Field(default_factory=FamilyInfo, description="诊断时的家庭信息")
    # 诊断结果
    result: Dict = Field(default_factory=dict, description="诊断结果详情")
    # 计费信息
    credits_used: int = Field(1, description="消耗的诊断次数")
    is_free: bool = Field(False, description="是否免费诊断")
    # 时间戳
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="诊断时间")
    # 关联支付记录（如果是付费诊断）
    payment_id: Optional[str] = Field(None, description="关联的支付记录ID")


# ============================================================
# 商品定价模型
# ============================================================

class ProductPricing(BaseModel):
    """商品定价配置"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="定价配置ID")
    credits: int = Field(0, description="诊断次数")
    price: float = Field(0.0, description="价格（元）")
    description: str = Field("", description="商品描述")
    is_active: bool = Field(True, description="是否启用")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="创建时间")
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="更新时间")


# ============================================================
# 数据持久化辅助函数
# ============================================================

def serialize_model(model: BaseModel) -> dict:
    """将Pydantic模型序列化为字典（用于JSON存储）"""
    return json.loads(model.json())


def deserialize_model(data: dict, model_class: type) -> BaseModel:
    """从字典反序列化为Pydantic模型"""
    return model_class(**data)


# ============================================================
# 数据文件路径常量
# ============================================================

DATA_DIR = Path(__file__).parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"
PAYMENTS_FILE = DATA_DIR / "payments.json"
DIAGNOSES_FILE = DATA_DIR / "diagnoses.json"
PRICING_FILE = DATA_DIR / "pricing.json"


def ensure_data_files():
    """确保数据文件存在"""
    DATA_DIR.mkdir(exist_ok=True)
    
    files = {
        USERS_FILE: [],
        PAYMENTS_FILE: [],
        DIAGNOSES_FILE: [],
        PRICING_FILE: [
            {
                "id": str(uuid.uuid4()),
                "credits": 1,
                "price": 9.9,
                "description": "单次诊断",
                "is_active": True,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            },
            {
                "id": str(uuid.uuid4()),
                "credits": 5,
                "price": 39.9,
                "description": "5次诊断包",
                "is_active": True,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            },
            {
                "id": str(uuid.uuid4()),
                "credits": 10,
                "price": 69.9,
                "description": "10次诊断包",
                "is_active": True,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
        ]
    }
    
    for file_path, default_content in files.items():
        if not file_path.exists():
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(default_content, f, ensure_ascii=False, indent=2)


# 导入json模块（用于序列化）
import json
from pathlib import Path


# 初始化数据文件
ensure_data_files()
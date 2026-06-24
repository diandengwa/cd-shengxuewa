#!/usr/bin/env python3
"""
支付相关数据模型：PaymentRecord（购买记录）、DiagnosisCreditConsumption（消耗记录）
包含订单号、用户ID、商品ID、金额、支付状态、创建时间等字段
"""

import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import Column, String, Integer, Float, DateTime, Enum, Text, Index, ForeignKey, Boolean, BigInteger
from sqlalchemy.dialects.sqlite import TEXT
from sqlalchemy.orm import declarative_base, relationship

import enum

# ============================================================
# 支付状态枚举
# ============================================================
class PaymentStatus(str, enum.Enum):
    """支付状态枚举"""
    PENDING = "pending"          # 待支付
    PAID = "paid"                # 已支付
    FAILED = "failed"            # 支付失败
    REFUNDED = "refunded"        # 已退款
    EXPIRED = "expired"          # 已过期
    CANCELLED = "cancelled"      # 已取消

# ============================================================
# 支付方式枚举
# ============================================================
class PaymentMethod(str, enum.Enum):
    """支付方式枚举"""
    WECHAT_PAY = "wechat_pay"    # 微信支付
    ALIPAY = "alipay"            # 支付宝
    BALANCE = "balance"          # 余额支付
    FREE = "free"                # 免费（内部赠送）

# ============================================================
# 商品类型枚举
# ============================================================
class ProductType(str, enum.Enum):
    """商品类型枚举"""
    DIAGNOSTIC = "diagnostic"    # 诊断服务
    REPORT = "report"            # 报告查看
    CONSULT = "consult"          # 咨询
    SUBSCRIPTION = "subscription" # 订阅
    OTHER = "other"              # 其他

# ============================================================
# 诊断消耗状态枚举
# ============================================================
class ConsumptionStatus(str, enum.Enum):
    """诊断消耗状态枚举"""
    PENDING = "pending"          # 待消耗
    CONSUMED = "consumed"        # 已消耗
    EXPIRED = "expired"          # 已过期
    REFUNDED = "refunded"        # 已退款

# ============================================================
# 诊断计费类型枚举
# ============================================================
class DiagnosticChargeType(str, enum.Enum):
    """诊断计费类型枚举"""
    SINGLE = "single"            # 单次诊断
    PACKAGE = "package"          # 套餐诊断
    SUBSCRIPTION = "subscription" # 订阅制诊断

# ============================================================
# 基础 ORM 模型
# ============================================================
Base = declarative_base()

class PaymentRecord(Base):
    """
    支付记录 ORM 模型
    
    记录每一次支付交易的完整信息，包括订单号、用户ID、商品ID、
    金额、支付状态、支付方式、创建时间等关键字段。
    
    支持按次诊断计费方案，每个诊断订单对应一条支付记录。
    """
    __tablename__ = "payment_records"
    
    # ============================================================
    # 主键与业务标识
    # ============================================================
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    
    # 订单号：唯一标识，格式：ORD + 时间戳 + 随机字符串
    order_no = Column(
        String(64), 
        unique=True, 
        nullable=False, 
        index=True,
        comment="订单号，全局唯一"
    )
    
    # 外部交易号（微信/支付宝等支付平台返回）
    transaction_id = Column(
        String(128), 
        nullable=True, 
        index=True,
        comment="支付平台交易号"
    )
    
    # ============================================================
    # 用户与商品关联
    # ============================================================
    user_id = Column(
        Integer, 
        nullable=False, 
        index=True,
        comment="用户ID，关联用户表"
    )
    
    # 商品ID：可以是诊断记录ID、报告ID等
    product_id = Column(
        String(64), 
        nullable=False, 
        index=True,
        comment="商品ID，关联具体商品/服务"
    )
    
    # 商品类型
    product_type = Column(
        String(32),
        nullable=False,
        default=ProductType.DIAGNOSTIC.value,
        comment="商品类型：diagnostic/report/consult/subscription/other"
    )
    
    # ============================================================
    # 金额信息（单位：分，避免浮点数精度问题）
    # ============================================================
    total_amount = Column(
        Integer, 
        nullable=False, 
        default=0,
        comment="订单总金额（单位：分）"
    )
    
    # 实际支付金额（考虑优惠后）
    pay_amount = Column(
        Integer, 
        nullable=False, 
        default=0,
        comment="实际支付金额（单位：分）"
    )
    
    # 优惠金额
    discount_amount = Column(
        Integer, 
        nullable=False, 
        default=0,
        comment="优惠金额（单位：分）"
    )
    
    # ============================================================
    # 支付状态与方式
    # ============================================================
    payment_status = Column(
        String(32),
        nullable=False,
        default=PaymentStatus.PENDING.value,
        index=True,
        comment="支付状态：pending/paid/failed/refunded/expired/cancelled"
    )
    
    payment_method = Column(
        String(32),
        nullable=True,
        comment="支付方式：wechat_pay/alipay/balance/free"
    )
    
    # ============================================================
    # 时间戳
    # ============================================================
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="创建时间（UTC）"
    )
    
    paid_at = Column(
        DateTime,
        nullable=True,
        comment="支付完成时间（UTC）"
    )
    
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间（UTC）"
    )
    
    # ============================================================
    # 扩展字段
    # ============================================================
    description = Column(
        Text,
        nullable=True,
        comment="订单描述"
    )
    
    remark = Column(
        Text,
        nullable=True,
        comment="备注信息"
    )
    
    # 是否删除（软删除）
    is_deleted = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否删除"
    )
    
    # ============================================================
    # 索引
    # ============================================================
    __table_args__ = (
        Index('idx_user_payment_status', 'user_id', 'payment_status'),
        Index('idx_product_payment', 'product_id', 'product_type'),
        Index('idx_created_at', 'created_at'),
    )
    
    # ============================================================
    # 关系
    # ============================================================
    consumption_records = relationship(
        "DiagnosisCreditConsumption",
        back_populates="payment_record",
        lazy="dynamic"
    )
    
    def __repr__(self):
        return f"<PaymentRecord(order_no={self.order_no}, user_id={self.user_id}, amount={self.pay_amount}, status={self.payment_status})>"


class DiagnosisCreditConsumption(Base):
    """
    诊断信用消耗记录 ORM 模型
    
    记录用户每次使用诊断服务时的信用消耗情况，
    支持按次计费、套餐计费和订阅制计费三种模式。
    """
    __tablename__ = "diagnosis_credit_consumptions"
    
    # ============================================================
    # 主键与业务标识
    # ============================================================
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    
    # 消耗记录唯一标识
    consumption_no = Column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="消耗记录编号，全局唯一"
    )
    
    # ============================================================
    # 关联信息
    # ============================================================
    user_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="用户ID"
    )
    
    # 关联的支付记录ID
    payment_id = Column(
        Integer,
        ForeignKey('payment_records.id'),
        nullable=True,
        index=True,
        comment="关联支付记录ID"
    )
    
    # 关联的诊断记录ID
    diagnosis_id = Column(
        String(64),
        nullable=False,
        index=True,
        comment="关联诊断记录ID"
    )
    
    # ============================================================
    # 计费信息
    # ============================================================
    # 计费类型
    charge_type = Column(
        String(32),
        nullable=False,
        default=DiagnosticChargeType.SINGLE.value,
        comment="计费类型：single/package/subscription"
    )
    
    # 消耗的信用点数（单位：分）
    credit_amount = Column(
        Integer,
        nullable=False,
        default=0,
        comment="消耗信用点数（单位：分）"
    )
    
    # 剩余信用点数（消耗后）
    remaining_credit = Column(
        Integer,
        nullable=False,
        default=0,
        comment="剩余信用点数（单位：分）"
    )
    
    # ============================================================
    # 消耗状态
    # ============================================================
    consumption_status = Column(
        String(32),
        nullable=False,
        default=ConsumptionStatus.PENDING.value,
        index=True,
        comment="消耗状态：pending/consumed/expired/refunded"
    )
    
    # ============================================================
    # 时间戳
    # ============================================================
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="创建时间（UTC）"
    )
    
    consumed_at = Column(
        DateTime,
        nullable=True,
        comment="消耗时间（UTC）"
    )
    
    expired_at = Column(
        DateTime,
        nullable=True,
        comment="过期时间（UTC）"
    )
    
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间（UTC）"
    )
    
    # ============================================================
    # 扩展字段
    # ============================================================
    description = Column(
        Text,
        nullable=True,
        comment="消耗描述"
    )
    
    remark = Column(
        Text,
        nullable=True,
        comment="备注信息"
    )
    
    # 是否删除（软删除）
    is_deleted = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否删除"
    )
    
    # ============================================================
    # 索引
    # ============================================================
    __table_args__ = (
        Index('idx_user_consumption', 'user_id', 'consumption_status'),
        Index('idx_diagnosis_consumption', 'diagnosis_id'),
        Index('idx_consumption_created', 'created_at'),
    )
    
    # ============================================================
    # 关系
    # ============================================================
    payment_record = relationship(
        "PaymentRecord",
        back_populates="consumption_records",
        foreign_keys=[payment_id]
    )
    
    def __repr__(self):
        return f"<DiagnosisCreditConsumption(consumption_no={self.consumption_no}, user_id={self.user_id}, credit={self.credit_amount}, status={self.consumption_status})>"


# ============================================================
# Pydantic 模型（用于API请求/响应验证）
# ============================================================
from pydantic import BaseModel, Field, validator
from typing import Optional

class PaymentCreate(BaseModel):
    """创建支付请求模型"""
    user_id: int = Field(..., description="用户ID")
    product_id: str = Field(..., description="商品ID")
    product_type: str = Field(default=ProductType.DIAGNOSTIC.value, description="商品类型")
    total_amount: int = Field(..., ge=0, description="订单总金额（单位：分）")
    pay_amount: int = Field(..., ge=0, description="实际支付金额（单位：分）")
    discount_amount: int = Field(default=0, ge=0, description="优惠金额（单位：分）")
    payment_method: Optional[str] = Field(None, description="支付方式")
    description: Optional[str] = Field(None, description="订单描述")
    
    @validator('pay_amount')
    def validate_pay_amount(cls, v, values):
        """验证支付金额不超过总金额"""
        if 'total_amount' in values and v > values['total_amount']:
            raise ValueError('支付金额不能超过总金额')
        return v
    
    @validator('discount_amount')
    def validate_discount_amount(cls, v, values):
        """验证优惠金额不超过总金额"""
        if 'total_amount' in values and v > values['total_amount']:
            raise ValueError('优惠金额不能超过总金额')
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 1,
                "product_id": "DIAG_20240101_001",
                "product_type": "diagnostic",
                "total_amount": 1000,
                "pay_amount": 1000,
                "discount_amount": 0,
                "payment_method": "wechat_pay",
                "description": "K12升学诊断服务"
            }
        }

class PaymentResponse(BaseModel):
    """支付响应模型"""
    id: int
    order_no: str
    user_id: int
    product_id: str
    product_type: str
    total_amount: int
    pay_amount: int
    discount_amount: int
    payment_status: str
    payment_method: Optional[str]
    created_at: datetime
    paid_at: Optional[datetime]
    description: Optional[str]
    
    class Config:
        from_attributes = True

class ConsumptionCreate(BaseModel):
    """创建消耗记录请求模型"""
    user_id: int = Field(..., description="用户ID")
    diagnosis_id: str = Field(..., description="诊断记录ID")
    payment_id: Optional[int] = Field(None, description="关联支付记录ID")
    charge_type: str = Field(default=DiagnosticChargeType.SINGLE.value, description="计费类型")
    credit_amount: int = Field(..., ge=0, description="消耗信用点数（单位：分）")
    remaining_credit: int = Field(default=0, ge=0, description="剩余信用点数（单位：分）")
    description: Optional[str] = Field(None, description="消耗描述")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 1,
                "diagnosis_id": "DIAG_20240101_001",
                "payment_id": 1,
                "charge_type": "single",
                "credit_amount": 500,
                "remaining_credit": 500,
                "description": "单次诊断服务消耗"
            }
        }

class ConsumptionResponse(BaseModel):
    """消耗记录响应模型"""
    id: int
    consumption_no: str
    user_id: int
    diagnosis_id: str
    payment_id: Optional[int]
    charge_type: str
    credit_amount: int
    remaining_credit: int
    consumption_status: str
    created_at: datetime
    consumed_at: Optional[datetime]
    expired_at: Optional[datetime]
    description: Optional[str]
    
    class Config:
        from_attributes = True

class PaymentListResponse(BaseModel):
    """支付记录列表响应模型"""
    total: int
    items: List[PaymentResponse]
    page: int
    page_size: int

class ConsumptionListResponse(BaseModel):
    """消耗记录列表响应模型"""
    total: int
    items: List[ConsumptionResponse]
    page: int
    page_size: int


# ============================================================
# 工具函数
# ============================================================
def generate_order_no() -> str:
    """
    生成唯一订单号
    
    格式：ORD + 14位时间戳(YYYYMMDDHHMMSS) + 8位随机字符串
    
    Returns:
        str: 唯一订单号
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = uuid.uuid4().hex[:8].upper()
    return f"ORD{timestamp}{random_str}"

def generate_consumption_no() -> str:
    """
    生成唯一消耗记录编号
    
    格式：CONS + 14位时间戳(YYYYMMDDHHMMSS) + 8位随机字符串
    
    Returns:
        str: 唯一消耗记录编号
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = uuid.uuid4().hex[:8].upper()
    return f"CONS{timestamp}{random_str}"

def calculate_discount(original_amount: int, discount_rate: float = 0.0) -> int:
    """
    计算优惠金额
    
    Args:
        original_amount: 原始金额（单位：分）
        discount_rate: 折扣率（0.0 ~ 1.0）
    
    Returns:
        int: 优惠金额（单位：分）
    """
    if discount_rate < 0 or discount_rate > 1:
        raise ValueError("折扣率必须在0到1之间")
    return int(original_amount * discount_rate)

def calculate_pay_amount(original_amount: int, discount_amount: int = 0) -> int:
    """
    计算实际支付金额
    
    Args:
        original_amount: 原始金额（单位：分）
        discount_amount: 优惠金额（单位：分）
    
    Returns:
        int: 实际支付金额（单位：分）
    """
    pay_amount = original_amount - discount_amount
    return max(pay_amount, 0)
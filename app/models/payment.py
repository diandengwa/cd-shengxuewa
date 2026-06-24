#!/usr/bin/env python3
"""
支付相关数据模型：PaymentRecord（购买记录）、DiagnosisCreditConsumption（消耗记录）
包含订单号、用户ID、商品ID、金额、支付状态、创建时间等字段
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Integer, Float, DateTime, Enum, Text, Index, ForeignKey, Boolean
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
    # 支付状态
    status = Column(
        String(32),
        nullable=False,
        default=PaymentStatus.PENDING.value,
        index=True,
        comment="支付状态：pending/paid/failed/refunded/expired/cancelled"
    )
    
    # 支付方式
    payment_method = Column(
        String(32),
        nullable=True,
        default=None,
        comment="支付方式：wechat_pay/alipay/balance/free"
    )
    
    # ============================================================
    # 时间戳
    # ============================================================
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="创建时间"
    )
    
    paid_at = Column(
        DateTime,
        nullable=True,
        default=None,
        comment="支付完成时间"
    )
    
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间"
    )
    
    # ============================================================
    # 扩展字段
    # ============================================================
    # 备注信息
    remark = Column(
        Text,
        nullable=True,
        default=None,
        comment="备注信息"
    )
    
    # 是否删除（软删除标记）
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
        Index('idx_user_status', 'user_id', 'status'),
        Index('idx_product_type', 'product_type', 'status'),
        Index('idx_created_at', 'created_at'),
    )
    
    # ============================================================
    # 关系
    # ============================================================
    # 关联的诊断消耗记录
    consumption_records = relationship(
        "DiagnosisCreditConsumption",
        back_populates="payment_record",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self):
        return f"<PaymentRecord(order_no='{self.order_no}', status='{self.status}', amount={self.pay_amount})>"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "order_no": self.order_no,
            "transaction_id": self.transaction_id,
            "user_id": self.user_id,
            "product_id": self.product_id,
            "product_type": self.product_type,
            "total_amount": self.total_amount,
            "pay_amount": self.pay_amount,
            "discount_amount": self.discount_amount,
            "status": self.status,
            "payment_method": self.payment_method,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "remark": self.remark
        }


class DiagnosisCreditConsumption(Base):
    """
    诊断次数消耗记录 ORM 模型
    
    记录用户每次使用诊断服务的消耗情况，包括关联的支付记录、
    消耗时间、消耗状态等。支持按次诊断计费方案。
    
    每次诊断消耗对应一条消耗记录，与支付记录关联。
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
    # 用户与支付记录关联
    # ============================================================
    user_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="用户ID，关联用户表"
    )
    
    # 关联的支付记录ID
    payment_record_id = Column(
        Integer,
        ForeignKey('payment_records.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
        comment="关联的支付记录ID"
    )
    
    # ============================================================
    # 诊断服务关联
    # ============================================================
    # 诊断记录ID（关联具体的诊断服务）
    diagnosis_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="诊断记录ID"
    )
    
    # 诊断类型
    diagnosis_type = Column(
        String(32),
        nullable=False,
        default="standard",
        comment="诊断类型：standard/premium/quick"
    )
    
    # ============================================================
    # 消耗信息
    # ============================================================
    # 消耗次数（默认1次）
    quantity = Column(
        Integer,
        nullable=False,
        default=1,
        comment="消耗次数"
    )
    
    # 消耗状态
    status = Column(
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
        comment="创建时间"
    )
    
    consumed_at = Column(
        DateTime,
        nullable=True,
        default=None,
        comment="消耗时间（实际使用时间）"
    )
    
    expired_at = Column(
        DateTime,
        nullable=True,
        default=None,
        comment="过期时间"
    )
    
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间"
    )
    
    # ============================================================
    # 扩展字段
    # ============================================================
    # 备注信息
    remark = Column(
        Text,
        nullable=True,
        default=None,
        comment="备注信息"
    )
    
    # 是否删除（软删除标记）
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
        Index('idx_consumption_user_status', 'user_id', 'status'),
        Index('idx_consumption_diagnosis', 'diagnosis_id'),
        Index('idx_consumption_created_at', 'created_at'),
    )
    
    # ============================================================
    # 关系
    # ============================================================
    # 关联的支付记录
    payment_record = relationship(
        "PaymentRecord",
        back_populates="consumption_records",
        lazy="joined"
    )
    
    def __repr__(self):
        return f"<DiagnosisCreditConsumption(consumption_no='{self.consumption_no}', status='{self.status}')>"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "consumption_no": self.consumption_no,
            "user_id": self.user_id,
            "payment_record_id": self.payment_record_id,
            "diagnosis_id": self.diagnosis_id,
            "diagnosis_type": self.diagnosis_type,
            "quantity": self.quantity,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "consumed_at": self.consumed_at.isoformat() if self.consumed_at else None,
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "remark": self.remark,
            "payment_record": self.payment_record.to_dict() if self.payment_record else None
        }


# ============================================================
# 工具函数
# ============================================================
def generate_order_no() -> str:
    """
    生成订单号
    
    格式：ORD + 时间戳(14位) + 随机字符串(6位)
    示例：ORD20231201123456A1B2C3
    
    Returns:
        str: 生成的订单号
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_str = secrets.token_hex(3).upper()  # 6位随机字符串
    return f"ORD{timestamp}{random_str}"


def generate_consumption_no() -> str:
    """
    生成消耗记录编号
    
    格式：CONS + 时间戳(14位) + 随机字符串(6位)
    示例：CONS20231201123456A1B2C3
    
    Returns:
        str: 生成的消耗记录编号
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_str = secrets.token_hex(3).upper()  # 6位随机字符串
    return f"CONS{timestamp}{random_str}"
#!/usr/bin/env python3
"""
K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋
支付记录ORM模型 — 记录购买/消耗诊断次数

付费模式重构 — 按次诊断计费方案 (Issue #26 Task A)
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Integer, Float, DateTime, Enum, ForeignKey, Text, Index
from sqlalchemy.dialects.sqlite import TEXT
from sqlalchemy.orm import relationship

from app.database import Base

# ============================================================
# 支付记录状态枚举
# ============================================================
class PaymentStatus:
    """支付状态常量"""
    PENDING = "pending"          # 待支付
    SUCCESS = "success"          # 支付成功
    FAILED = "failed"            # 支付失败
    REFUNDED = "refunded"        # 已退款
    EXPIRED = "expired"          # 已过期

# ============================================================
# 诊断次数操作类型
# ============================================================
class DiagnosisOperationType:
    """诊断次数操作类型"""
    PURCHASE = "purchase"        # 购买次数
    CONSUME = "consume"          # 消耗次数
    REFUND = "refund"            # 退款退回
    ADMIN_ADJUST = "admin_adjust" # 管理员调整
    EXPIRATION = "expiration"    # 过期扣除

# ============================================================
# 支付记录ORM模型
# ============================================================
class PaymentRecord(Base):
    """
    支付记录表
    记录用户购买诊断次数的支付流水，以及诊断次数的消耗记录
    """
    __tablename__ = "payment_records"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True, comment="记录ID")
    
    # 唯一标识（对外暴露）
    record_id = Column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
        comment="记录唯一标识（UUID）"
    )
    
    # 用户关联
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID"
    )
    
    # 订单关联（可选）
    order_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="外部订单号（微信支付订单号）"
    )
    
    # 支付信息
    amount = Column(
        Float(precision=2),
        nullable=False,
        default=0.0,
        comment="支付金额（元）"
    )
    
    diagnosis_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="诊断次数（正数=购买/增加，负数=消耗/减少）"
    )
    
    operation_type = Column(
        String(20),
        nullable=False,
        default=DiagnosisOperationType.PURCHASE,
        comment="操作类型：purchase/consume/refund/admin_adjust/expiration"
    )
    
    status = Column(
        String(20),
        nullable=False,
        default=PaymentStatus.PENDING,
        comment="支付状态：pending/success/failed/refunded/expired"
    )
    
    # 支付方式
    payment_method = Column(
        String(32),
        nullable=True,
        comment="支付方式：wechat_pay/alipay/balance/admin"
    )
    
    # 支付时间
    paid_at = Column(
        DateTime,
        nullable=True,
        comment="支付完成时间"
    )
    
    # 过期时间（诊断次数有效期）
    expires_at = Column(
        DateTime,
        nullable=True,
        comment="诊断次数过期时间（NULL表示永久有效）"
    )
    
    # 备注信息
    remark = Column(
        Text,
        nullable=True,
        comment="备注信息（如：购买套餐名称、消耗原因等）"
    )
    
    # 扩展字段（JSON格式存储额外信息）
    extra_data = Column(
        Text,
        nullable=True,
        comment="扩展数据（JSON格式，存储支付回调原始数据等）"
    )
    
    # 时间戳
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="创建时间"
    )
    
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间"
    )

    # ============================================================
    # 关系定义
    # ============================================================
    user = relationship("User", back_populates="payment_records")

    # ============================================================
    # 索引
    # ============================================================
    __table_args__ = (
        Index("idx_payment_user_status", "user_id", "status"),
        Index("idx_payment_created_at", "created_at"),
        Index("idx_payment_operation_type", "operation_type"),
    )

    # ============================================================
    # 实例方法
    # ============================================================
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "record_id": self.record_id,
            "user_id": self.user_id,
            "order_id": self.order_id,
            "amount": self.amount,
            "diagnosis_count": self.diagnosis_count,
            "operation_type": self.operation_type,
            "status": self.status,
            "payment_method": self.payment_method,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "remark": self.remark,
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def mark_paid(self, order_id: str = None, payment_method: str = None) -> None:
        """
        标记为已支付
        
        Args:
            order_id: 外部订单号
            payment_method: 支付方式
        """
        self.status = PaymentStatus.SUCCESS
        self.paid_at = datetime.utcnow()
        if order_id:
            self.order_id = order_id
        if payment_method:
            self.payment_method = payment_method

    def mark_failed(self, remark: str = None) -> None:
        """
        标记为支付失败
        
        Args:
            remark: 失败原因
        """
        self.status = PaymentStatus.FAILED
        if remark:
            self.remark = remark

    def mark_refunded(self, remark: str = None) -> None:
        """
        标记为已退款
        
        Args:
            remark: 退款原因
        """
        self.status = PaymentStatus.REFUNDED
        if remark:
            self.remark = remark

    def mark_expired(self) -> None:
        """标记为已过期"""
        self.status = PaymentStatus.EXPIRED

    def is_paid(self) -> bool:
        """是否已支付成功"""
        return self.status == PaymentStatus.SUCCESS

    def is_consumable(self) -> bool:
        """
        是否可消耗（判断诊断次数是否可用）
        
        Returns:
            bool: 如果已支付且未过期，返回True
        """
        if self.status != PaymentStatus.SUCCESS:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True

    def get_remaining_days(self) -> Optional[int]:
        """
        获取剩余有效天数
        
        Returns:
            Optional[int]: 剩余天数，永久有效返回None
        """
        if not self.expires_at:
            return None
        remaining = (self.expires_at - datetime.utcnow()).days
        return max(0, remaining)

    def __repr__(self) -> str:
        return (
            f"<PaymentRecord(id={self.id}, "
            f"user_id={self.user_id}, "
            f"amount={self.amount}, "
            f"diagnosis_count={self.diagnosis_count}, "
            f"operation_type={self.operation_type}, "
            f"status={self.status})>"
        )


# ============================================================
# 用户诊断次数汇总视图（可选，用于快速查询用户剩余次数）
# ============================================================
class UserDiagnosisSummary(Base):
    """
    用户诊断次数汇总表（物化视图替代方案）
    定期更新或通过触发器维护，用于快速查询用户剩余诊断次数
    """
    __tablename__ = "user_diagnosis_summary"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="记录ID")
    
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="用户ID"
    )
    
    total_purchased = Column(
        Integer,
        nullable=False,
        default=0,
        comment="累计购买次数"
    )
    
    total_consumed = Column(
        Integer,
        nullable=False,
        default=0,
        comment="累计消耗次数"
    )
    
    total_refunded = Column(
        Integer,
        nullable=False,
        default=0,
        comment="累计退款次数"
    )
    
    remaining_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="剩余可用次数"
    )
    
    last_purchase_at = Column(
        DateTime,
        nullable=True,
        comment="最近购买时间"
    )
    
    last_consume_at = Column(
        DateTime,
        nullable=True,
        comment="最近消耗时间"
    )
    
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间"
    )

    # ============================================================
    # 关系定义
    # ============================================================
    user = relationship("User", back_populates="diagnosis_summary")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "total_purchased": self.total_purchased,
            "total_consumed": self.total_consumed,
            "total_refunded": self.total_refunded,
            "remaining_count": self.remaining_count,
            "last_purchase_at": self.last_purchase_at.isoformat() if self.last_purchase_at else None,
            "last_consume_at": self.last_consume_at.isoformat() if self.last_consume_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<UserDiagnosisSummary(user_id={self.user_id}, "
            f"remaining_count={self.remaining_count})>"
        )
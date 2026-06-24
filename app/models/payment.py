#!/usr/bin/env python3
"""
支付相关数据模型：PaymentRecord ORM模型
包含订单号、用户ID、商品ID、金额、支付状态、创建时间等字段
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Integer, Float, DateTime, Enum, Text, Index
from sqlalchemy.dialects.sqlite import TEXT
from sqlalchemy.orm import declarative_base

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
        comment="支付方式：wechat_pay/alipay/balance/free"
    )
    
    # ============================================================
    # 时间戳
    # ============================================================
    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="记录创建时间（UTC）"
    )
    
    # 支付完成时间
    paid_at = Column(
        DateTime,
        nullable=True,
        comment="支付完成时间（UTC）"
    )
    
    # 更新时间
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="记录更新时间（UTC）"
    )
    
    # ============================================================
    # 扩展字段
    # ============================================================
    # 备注信息
    remark = Column(
        Text,
        nullable=True,
        comment="备注信息"
    )
    
    # 附加数据（JSON格式，存储额外信息）
    extra_data = Column(
        Text,
        nullable=True,
        comment="附加数据（JSON格式）"
    )
    
    # ============================================================
    # 索引优化
    # ============================================================
    __table_args__ = (
        # 复合索引：用户ID + 状态，用于查询用户订单列表
        Index('idx_user_status', 'user_id', 'status'),
        # 复合索引：商品ID + 类型，用于查询商品支付记录
        Index('idx_product_type', 'product_id', 'product_type'),
        # 复合索引：创建时间 + 状态，用于统计和报表
        Index('idx_created_status', 'created_at', 'status'),
    )
    
    # ============================================================
    # 实例方法
    # ============================================================
    def to_dict(self) -> dict:
        """
        将模型实例转换为字典
        
        Returns:
            dict: 包含所有字段的字典
        """
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
            "remark": self.remark,
            "extra_data": self.extra_data,
        }
    
    def to_json(self) -> str:
        """
        将模型实例转换为JSON字符串
        
        Returns:
            str: JSON格式的字符串
        """
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)
    
    def mark_paid(self, transaction_id: str = None, payment_method: str = None) -> None:
        """
        标记订单为已支付
        
        Args:
            transaction_id: 支付平台交易号
            payment_method: 支付方式
        """
        self.status = PaymentStatus.PAID.value
        self.paid_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        if transaction_id:
            self.transaction_id = transaction_id
        if payment_method:
            self.payment_method = payment_method
    
    def mark_failed(self, remark: str = None) -> None:
        """
        标记订单为支付失败
        
        Args:
            remark: 失败原因备注
        """
        self.status = PaymentStatus.FAILED.value
        self.updated_at = datetime.utcnow()
        if remark:
            self.remark = remark
    
    def mark_refunded(self, remark: str = None) -> None:
        """
        标记订单为已退款
        
        Args:
            remark: 退款原因备注
        """
        self.status = PaymentStatus.REFUNDED.value
        self.updated_at = datetime.utcnow()
        if remark:
            self.remark = remark
    
    def mark_expired(self) -> None:
        """标记订单为已过期"""
        self.status = PaymentStatus.EXPIRED.value
        self.updated_at = datetime.utcnow()
    
    def mark_cancelled(self, remark: str = None) -> None:
        """
        标记订单为已取消
        
        Args:
            remark: 取消原因备注
        """
        self.status = PaymentStatus.CANCELLED.value
        self.updated_at = datetime.utcnow()
        if remark:
            self.remark = remark
    
    def is_paid(self) -> bool:
        """
        检查订单是否已支付
        
        Returns:
            bool: 是否已支付
        """
        return self.status == PaymentStatus.PAID.value
    
    def is_pending(self) -> bool:
        """
        检查订单是否待支付
        
        Returns:
            bool: 是否待支付
        """
        return self.status == PaymentStatus.PENDING.value
    
    def can_pay(self) -> bool:
        """
        检查订单是否可支付（待支付状态且未过期）
        
        Returns:
            bool: 是否可支付
        """
        return self.status == PaymentStatus.PENDING.value
    
    def __repr__(self) -> str:
        """模型字符串表示"""
        return (
            f"<PaymentRecord("
            f"id={self.id}, "
            f"order_no='{self.order_no}', "
            f"user_id={self.user_id}, "
            f"product_id='{self.product_id}', "
            f"amount={self.pay_amount}, "
            f"status='{self.status}'"
            f")>"
        )


# ============================================================
# 辅助函数：生成订单号
# ============================================================
def generate_order_no() -> str:
    """
    生成唯一订单号
    
    格式：ORD + 14位时间戳(YYYYMMDDHHMMSS) + 6位随机字符串
    
    Returns:
        str: 唯一订单号
    """
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d%H%M%S")
    # 生成6位随机字符串（字母数字混合）
    random_str = uuid.uuid4().hex[:6].upper()
    return f"ORD{timestamp}{random_str}"


# ============================================================
# 辅助函数：金额单位转换
# ============================================================
def yuan_to_fen(amount: float) -> int:
    """
    将元转换为分
    
    Args:
        amount: 金额（元）
    
    Returns:
        int: 金额（分）
    """
    return int(round(amount * 100))


def fen_to_yuan(amount: int) -> float:
    """
    将分转换为元
    
    Args:
        amount: 金额（分）
    
    Returns:
        float: 金额（元）
    """
    return round(amount / 100, 2)
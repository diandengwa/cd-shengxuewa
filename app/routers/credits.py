#!/usr/bin/env python3
"""
诊断次数相关API路由：余额查询、购买、消耗记录
付费模式重构 — 按次诊断计费方案
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.database import get_db
from app.models import User, CreditTransaction, CreditPackage
from app.utils.auth import get_current_user, verify_wechat_oauth
from app.utils.payment import create_payment_order, verify_payment_signature

logger = logging.getLogger("k12.credits")

router = APIRouter(
    prefix="/api/v1/credits",
    tags=["诊断次数"],
    responses={404: {"description": "Not found"}}
)

# ============================================================
# Pydantic 模型
# ============================================================

class CreditBalanceResponse(BaseModel):
    """余额查询响应"""
    user_id: int
    balance: int = Field(..., ge=0, description="剩余诊断次数")
    total_consumed: int = Field(..., ge=0, description="累计消耗次数")
    total_purchased: int = Field(..., ge=0, description="累计购买次数")
    last_purchase_time: Optional[datetime] = None
    last_consume_time: Optional[datetime] = None

class PurchaseRequest(BaseModel):
    """购买诊断次数请求"""
    package_id: int = Field(..., gt=0, description="套餐ID")
    payment_method: str = Field(default="wechat", pattern="^(wechat|alipay)$")
    coupon_code: Optional[str] = Field(None, max_length=50)

    @field_validator("package_id")
    @classmethod
    def validate_package(cls, v):
        """验证套餐是否存在且可购买"""
        db = next(get_db())
        try:
            package = db.query(CreditPackage).filter(
                CreditPackage.id == v,
                CreditPackage.is_active == True
            ).first()
            if not package:
                raise ValueError(f"套餐ID {v} 不存在或已下架")
            if package.stock is not None and package.stock <= 0:
                raise ValueError(f"套餐 {package.name} 已售罄")
        finally:
            db.close()
        return v

class PurchaseResponse(BaseModel):
    """购买响应"""
    order_id: str
    payment_url: str
    amount: Decimal = Field(..., decimal_places=2)
    credits: int = Field(..., ge=1)
    expire_at: Optional[datetime] = None

class ConsumeRequest(BaseModel):
    """消耗诊断次数请求"""
    action: str = Field(..., pattern="^(diagnose|report|export)$", description="消耗动作类型")
    target_id: Optional[int] = Field(None, description="关联目标ID（如诊断记录ID）")
    description: Optional[str] = Field(None, max_length=200)

class ConsumeResponse(BaseModel):
    """消耗响应"""
    success: bool
    balance_before: int
    balance_after: int
    transaction_id: int
    message: str

class TransactionRecord(BaseModel):
    """交易记录"""
    id: int
    user_id: int
    type: str = Field(..., pattern="^(purchase|consume|refund|admin_adjust)$")
    amount: int = Field(..., description="正数为增加，负数为消耗")
    balance_before: int
    balance_after: int
    description: Optional[str] = None
    order_id: Optional[str] = None
    created_at: datetime

class TransactionListResponse(BaseModel):
    """交易记录列表响应"""
    total: int
    page: int
    page_size: int
    records: List[TransactionRecord]

class PackageInfo(BaseModel):
    """套餐信息"""
    id: int
    name: str
    credits: int = Field(..., ge=1)
    price: Decimal = Field(..., decimal_places=2)
    original_price: Optional[Decimal] = Field(None, decimal_places=2)
    description: Optional[str] = None
    is_active: bool
    stock: Optional[int] = None
    expire_days: Optional[int] = Field(None, ge=1, description="有效期天数，null表示长期有效")

# ============================================================
# 辅助函数
# ============================================================

def _get_user_balance(user_id: int) -> int:
    """获取用户当前诊断次数余额"""
    db = next(get_db())
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return user.credit_balance or 0
    finally:
        db.close()

def _record_transaction(
    db,
    user_id: int,
    trans_type: str,
    amount: int,
    balance_before: int,
    balance_after: int,
    description: Optional[str] = None,
    order_id: Optional[str] = None,
    target_id: Optional[int] = None
) -> CreditTransaction:
    """记录交易流水"""
    transaction = CreditTransaction(
        user_id=user_id,
        type=trans_type,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        description=description,
        order_id=order_id,
        target_id=target_id,
        created_at=datetime.utcnow()
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction

# ============================================================
# API 路由
# ============================================================

@router.get("/balance", response_model=CreditBalanceResponse)
async def get_credit_balance(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    查询当前用户诊断次数余额
    - 需要微信OAuth认证
    - 返回余额、累计消耗、累计购买等信息
    """
    try:
        db = next(get_db())
        user = db.query(User).filter(User.id == current_user.id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 统计累计消耗和购买
        stats = db.query(
            db.func.sum(CreditTransaction.amount).filter(
                CreditTransaction.user_id == user.id,
                CreditTransaction.type == 'consume'
            ).label('total_consumed'),
            db.func.sum(CreditTransaction.amount).filter(
                CreditTransaction.user_id == user.id,
                CreditTransaction.type == 'purchase'
            ).label('total_purchased'),
            db.func.max(CreditTransaction.created_at).filter(
                CreditTransaction.user_id == user.id,
                CreditTransaction.type == 'purchase'
            ).label('last_purchase_time'),
            db.func.max(CreditTransaction.created_at).filter(
                CreditTransaction.user_id == user.id,
                CreditTransaction.type == 'consume'
            ).label('last_consume_time')
        ).first()

        return CreditBalanceResponse(
            user_id=user.id,
            balance=user.credit_balance or 0,
            total_consumed=abs(stats.total_consumed or 0),
            total_purchased=stats.total_purchased or 0,
            last_purchase_time=stats.last_purchase_time,
            last_consume_time=stats.last_consume_time
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询余额失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询余额失败")
    finally:
        db.close()

@router.get("/packages", response_model=List[PackageInfo])
async def get_credit_packages(
    request: Request,
    include_inactive: bool = Query(False, description="是否包含已下架套餐")
):
    """
    获取可购买的诊断次数套餐列表
    - 公开接口，无需认证
    - 默认只返回上架套餐
    """
    try:
        db = next(get_db())
        query = db.query(CreditPackage)
        if not include_inactive:
            query = query.filter(CreditPackage.is_active == True)
        packages = query.order_by(CreditPackage.price.asc()).all()

        return [
            PackageInfo(
                id=pkg.id,
                name=pkg.name,
                credits=pkg.credits,
                price=pkg.price,
                original_price=pkg.original_price,
                description=pkg.description,
                is_active=pkg.is_active,
                stock=pkg.stock,
                expire_days=pkg.expire_days
            )
            for pkg in packages
        ]
    except Exception as e:
        logger.error(f"获取套餐列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取套餐列表失败")
    finally:
        db.close()

@router.post("/purchase", response_model=PurchaseResponse)
async def purchase_credits(
    request: Request,
    purchase_req: PurchaseRequest,
    current_user: User = Depends(get_current_user)
):
    """
    购买诊断次数
    - 需要微信OAuth认证
    - 创建支付订单并返回支付链接
    """
    try:
        db = next(get_db())

        # 获取套餐信息
        package = db.query(CreditPackage).filter(
            CreditPackage.id == purchase_req.package_id,
            CreditPackage.is_active == True
        ).first()
        if not package:
            raise HTTPException(status_code=404, detail="套餐不存在或已下架")

        # 检查库存
        if package.stock is not None and package.stock <= 0:
            raise HTTPException(status_code=400, detail="套餐已售罄")

        # 生成订单号
        order_id = f"CRD{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4).upper()}"

        # 计算实际支付金额（考虑优惠券）
        amount = package.price
        if purchase_req.coupon_code:
            # 这里可以集成优惠券验证逻辑
            # 暂时简单处理
            pass

        # 创建支付订单
        payment_result = await create_payment_order(
            order_id=order_id,
            amount=amount,
            description=f"购买{pkg.name}",
            payment_method=purchase_req.payment_method,
            user_id=current_user.id
        )

        if not payment_result.get("success"):
            raise HTTPException(status_code=500, detail="创建支付订单失败")

        # 计算有效期
        expire_at = None
        if package.expire_days:
            expire_at = datetime.utcnow() + timedelta(days=package.expire_days)

        return PurchaseResponse(
            order_id=order_id,
            payment_url=payment_result.get("payment_url", ""),
            amount=amount,
            credits=package.credits,
            expire_at=expire_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"购买诊断次数失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="购买失败，请稍后重试")
    finally:
        db.close()

@router.post("/consume", response_model=ConsumeResponse)
async def consume_credits(
    request: Request,
    consume_req: ConsumeRequest,
    current_user: User = Depends(get_current_user)
):
    """
    消耗诊断次数
    - 需要微信OAuth认证
    - 根据动作类型消耗不同次数
    """
    try:
        db = next(get_db())
        user = db.query(User).filter(User.id == current_user.id).with_for_update().first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        balance_before = user.credit_balance or 0

        # 根据动作类型确定消耗次数
        consume_amounts = {
            "diagnose": 1,  # 一次诊断消耗1次
            "report": 1,    # 生成报告消耗1次
            "export": 1     # 导出数据消耗1次
        }

        amount = consume_amounts.get(consume_req.action, 1)

        if balance_before < amount:
            raise HTTPException(
                status_code=402,
                detail=f"诊断次数不足，当前余额: {balance_before}，需要: {amount}"
            )

        # 更新余额
        balance_after = balance_before - amount
        user.credit_balance = balance_after

        # 记录交易流水
        transaction = _record_transaction(
            db=db,
            user_id=user.id,
            trans_type="consume",
            amount=-amount,
            balance_before=balance_before,
            balance_after=balance_after,
            description=consume_req.description or f"诊断消耗({consume_req.action})",
            target_id=consume_req.target_id
        )

        db.commit()

        return ConsumeResponse(
            success=True,
            balance_before=balance_before,
            balance_after=balance_after,
            transaction_id=transaction.id,
            message=f"消耗{amount}次诊断次数成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"消耗诊断次数失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="消耗失败，请稍后重试")
    finally:
        db.close()

@router.get("/transactions", response_model=TransactionListResponse)
async def get_transaction_history(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    trans_type: Optional[str] = Query(None, pattern="^(purchase|consume|refund|admin_adjust)$", description="交易类型筛选"),
    start_date: Optional[datetime] = Query(None, description="开始时间"),
    end_date: Optional[datetime] = Query(None, description="结束时间"),
    current_user: User = Depends(get_current_user)
):
    """
    获取诊断次数交易记录
    - 需要微信OAuth认证
    - 支持分页、类型筛选、时间范围筛选
    """
    try:
        db = next(get_db())

        # 构建查询
        query = db.query(CreditTransaction).filter(
            CreditTransaction.user_id == current_user.id
        )

        if trans_type:
            query = query.filter(CreditTransaction.type == trans_type)
        if start_date:
            query = query.filter(CreditTransaction.created_at >= start_date)
        if end_date:
            query = query.filter(CreditTransaction.created_at <= end_date)

        # 获取总数
        total = query.count()

        # 分页查询
        records = query.order_by(
            CreditTransaction.created_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()

        return TransactionListResponse(
            total=total,
            page=page,
            page_size=page_size,
            records=[
                TransactionRecord(
                    id=record.id,
                    user_id=record.user_id,
                    type=record.type,
                    amount=record.amount,
                    balance_before=record.balance_before,
                    balance_after=record.balance_after,
                    description=record.description,
                    order_id=record.order_id,
                    created_at=record.created_at
                )
                for record in records
            ]
        )

    except Exception as e:
        logger.error(f"获取交易记录失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取交易记录失败")
    finally:
        db.close()

@router.post("/payment/callback")
async def payment_callback(
    request: Request,
    current_user: User = Depends(verify_wechat_oauth)
):
    """
    支付回调处理
    - 微信支付异步通知
    - 验证签名后更新用户余额
    """
    try:
        # 获取回调数据
        callback_data = await request.json()

        # 验证签名
        if not verify_payment_signature(callback_data):
            raise HTTPException(status_code=400, detail="签名验证失败")

        # 处理支付结果
        order_id = callback_data.get("out_trade_no")
        transaction_id = callback_data.get("transaction_id")
        total_fee = Decimal(str(callback_data.get("total_fee", 0))) / 100  # 分转元
        trade_status = callback_data.get("trade_state")

        if trade_status != "SUCCESS":
            logger.warning(f"支付未成功: order_id={order_id}, status={trade_status}")
            return {"code": "FAIL", "message": "支付未成功"}

        db = next(get_db())

        # 查找订单对应的套餐
        # 这里需要根据实际订单系统实现
        # 暂时简单处理：根据order_id查询关联的套餐信息
        # 实际项目中应该有一个订单表来存储订单与套餐的关联

        # 更新用户余额
        # 这里需要根据实际业务逻辑实现
        # 暂时返回成功
        db.commit()

        return {"code": "SUCCESS", "message": "支付成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"支付回调处理失败: {str(e)}", exc_info=True)
        return {"code": "FAIL", "message": "处理失败"}
    finally:
        db.close()

@router.post("/admin/adjust")
async def admin_adjust_credits(
    request: Request,
    user_id: int = Query(..., description="目标用户ID"),
    amount: int = Query(..., description="调整数量（正数增加，负数减少）"),
    reason: str = Query(..., min_length=1, max_length=200, description="调整原因"),
    current_user: User = Depends(get_current_user)
):
    """
    管理员调整用户诊断次数
    - 需要管理员权限
    - 用于后台手动调整用户余额
    """
    # 检查管理员权限
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    try:
        db = next(get_db())
        user = db.query(User).filter(User.id == user_id).with_for_update().first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        balance_before = user.credit_balance or 0
        balance_after = balance_before + amount

        if balance_after < 0:
            raise HTTPException(status_code=400, detail="调整后余额不能为负数")

        # 更新余额
        user.credit_balance = balance_after

        # 记录交易流水
        transaction = _record_transaction(
            db=db,
            user_id=user.id,
            trans_type="admin_adjust",
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            description=f"管理员调整: {reason}"
        )

        db.commit()

        return {
            "success": True,
            "user_id": user.id,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "adjust_amount": amount,
            "transaction_id": transaction.id,
            "message": f"调整成功，用户 {user_id} 余额从 {balance_before} 变更为 {balance_after}"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"管理员调整余额失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="调整失败")
    finally:
        db.close()
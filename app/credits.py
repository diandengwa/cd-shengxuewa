#!/usr/bin/env python3
"""
诊断次数管理模块：扣减/增加credits、检查余额、免费额度管理
用于成都K12升学参谋（cd-shengxuewa）付费模式重构 — 按次诊断计费方案
支持免费查询和深度诊断两种计费模式
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.database import get_db
from app.models import User, CreditTransaction, CreditPlan
from app.schemas import CreditBalanceResponse, CreditDeductRequest, CreditDeductResponse

logger = logging.getLogger(__name__)

# ============================================================
# 常量定义
# ============================================================
FREE_DAILY_CREDITS = 3  # 每日免费诊断次数
FREE_TRIAL_CREDITS = 5  # 新用户注册赠送次数
CREDIT_EXPIRY_DAYS = 30  # 购买额度有效期（天）

# 诊断类型及其消耗额度
DIAGNOSTIC_COST = {
    "free_query": 0,      # 免费查询，不消耗额度
    "basic_diagnosis": 1, # 基础诊断，消耗1次额度
    "deep_diagnosis": 3   # 深度诊断，消耗3次额度
}

# 诊断类型分类
DIAGNOSTIC_TYPES = {
    "free": ["free_query"],                    # 免费类型
    "paid": ["basic_diagnosis", "deep_diagnosis"]  # 付费类型
}

# ============================================================
# 免费额度管理
# ============================================================

async def get_free_daily_credits(user_id: int, db: Session) -> int:
    """
    获取用户每日免费额度
    返回当日剩余免费次数（仅针对免费查询类型）
    """
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # 查询今日已使用的免费查询次数
        used_today = db.query(func.count(CreditTransaction.id)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type == "free_query",
                CreditTransaction.created_at >= today_start,
                CreditTransaction.created_at < today_end,
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0

        remaining = max(0, FREE_DAILY_CREDITS - used_today)
        logger.info(f"用户 {user_id} 今日免费查询额度剩余: {remaining}")
        return remaining

    except Exception as e:
        logger.error(f"获取免费额度失败: {str(e)}", exc_info=True)
        return 0


async def grant_trial_credits(user_id: int, db: Session) -> bool:
    """
    为新用户赠送试用额度
    返回是否成功
    """
    try:
        # 检查是否已赠送过
        existing = db.query(CreditTransaction).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type == "trial",
                CreditTransaction.status == "completed"
            )
        ).first()

        if existing:
            logger.info(f"用户 {user_id} 已领取过试用额度，跳过")
            return False

        # 创建赠送记录
        transaction = CreditTransaction(
            user_id=user_id,
            amount=FREE_TRIAL_CREDITS,
            transaction_type="trial",
            description="新用户注册赠送",
            status="completed",
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=CREDIT_EXPIRY_DAYS)
        )
        db.add(transaction)

        # 更新用户额度
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.credit_balance = (user.credit_balance or 0) + FREE_TRIAL_CREDITS
            user.updated_at = datetime.now()

        db.commit()
        logger.info(f"用户 {user_id} 成功领取 {FREE_TRIAL_CREDITS} 次试用额度")
        return True

    except Exception as e:
        db.rollback()
        logger.error(f"赠送试用额度失败: {str(e)}", exc_info=True)
        return False


# ============================================================
# 余额检查
# ============================================================

async def check_credit_balance(user_id: int, db: Session) -> CreditBalanceResponse:
    """
    检查用户可用额度余额
    返回包含免费额度、付费额度、总余额的响应
    """
    try:
        # 获取用户信息
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        # 获取免费额度（免费查询次数）
        free_credits = await get_free_daily_credits(user_id, db)

        # 获取付费额度（未过期的）
        now = datetime.now()
        paid_credits = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["purchase", "trial"]),
                CreditTransaction.status == "completed",
                or_(
                    CreditTransaction.expires_at.is_(None),
                    CreditTransaction.expires_at > now
                )
            )
        ).scalar() or 0

        # 计算已使用的付费额度
        used_paid = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["basic_diagnosis", "deep_diagnosis"]),
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0

        # 计算可用付费额度
        available_paid = max(0, paid_credits - used_paid)

        # 计算总余额（免费 + 付费）
        total_balance = free_credits + available_paid

        return CreditBalanceResponse(
            user_id=user_id,
            free_credits=free_credits,
            paid_credits=available_paid,
            total_balance=total_balance,
            daily_limit=FREE_DAILY_CREDITS,
            daily_used=FREE_DAILY_CREDITS - free_credits
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检查余额失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="检查余额失败"
        )


# ============================================================
# 诊断类型判断
# ============================================================

def is_free_diagnostic(diagnostic_type: str) -> bool:
    """
    判断是否为免费诊断类型
    """
    return diagnostic_type in DIAGNOSTIC_TYPES["free"]


def get_diagnostic_cost(diagnostic_type: str) -> int:
    """
    获取指定诊断类型的消耗额度
    """
    return DIAGNOSTIC_COST.get(diagnostic_type, 0)


# ============================================================
# 额度扣减
# ============================================================

async def deduct_credits(
    user_id: int,
    diagnostic_type: str,
    db: Session,
    description: Optional[str] = None
) -> CreditDeductResponse:
    """
    扣减用户诊断额度
    支持免费查询和深度诊断两种模式
    """
    try:
        # 获取诊断消耗额度
        cost = get_diagnostic_cost(diagnostic_type)
        
        # 如果是免费类型，直接返回成功
        if is_free_diagnostic(diagnostic_type):
            # 检查免费额度是否足够
            free_remaining = await get_free_daily_credits(user_id, db)
            if free_remaining <= 0:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="今日免费查询次数已用完"
                )
            
            # 记录免费查询交易
            transaction = CreditTransaction(
                user_id=user_id,
                amount=0,
                transaction_type=diagnostic_type,
                description=description or "免费查询",
                status="completed",
                created_at=datetime.now()
            )
            db.add(transaction)
            db.commit()
            
            return CreditDeductResponse(
                success=True,
                deducted=0,
                remaining_free=free_remaining - 1,
                remaining_paid=await get_paid_credits_balance(user_id, db),
                diagnostic_type=diagnostic_type
            )

        # 付费诊断逻辑
        # 检查用户是否存在
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        # 检查付费额度是否足够
        paid_balance = await get_paid_credits_balance(user_id, db)
        if paid_balance < cost:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"付费额度不足，需要 {cost} 次，当前剩余 {paid_balance} 次"
            )

        # 创建扣减记录
        transaction = CreditTransaction(
            user_id=user_id,
            amount=-cost,
            transaction_type=diagnostic_type,
            description=description or f"{diagnostic_type}诊断消耗",
            status="completed",
            created_at=datetime.now()
        )
        db.add(transaction)

        # 更新用户余额
        user.credit_balance = (user.credit_balance or 0) - cost
        user.updated_at = datetime.now()

        db.commit()
        
        # 获取更新后的余额
        new_paid_balance = await get_paid_credits_balance(user_id, db)
        
        logger.info(f"用户 {user_id} 完成 {diagnostic_type} 诊断，消耗 {cost} 次额度")
        
        return CreditDeductResponse(
            success=True,
            deducted=cost,
            remaining_free=await get_free_daily_credits(user_id, db),
            remaining_paid=new_paid_balance,
            diagnostic_type=diagnostic_type
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"扣减额度失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="扣减额度失败"
        )


# ============================================================
# 付费额度查询
# ============================================================

async def get_paid_credits_balance(user_id: int, db: Session) -> int:
    """
    获取用户可用付费额度余额
    """
    try:
        now = datetime.now()
        
        # 获取总付费额度（购买+赠送，未过期）
        total_paid = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["purchase", "trial"]),
                CreditTransaction.status == "completed",
                or_(
                    CreditTransaction.expires_at.is_(None),
                    CreditTransaction.expires_at > now
                )
            )
        ).scalar() or 0

        # 获取已使用的付费额度
        used_paid = db.query(func.sum(func.abs(CreditTransaction.amount))).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["basic_diagnosis", "deep_diagnosis"]),
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0

        return max(0, total_paid - used_paid)

    except Exception as e:
        logger.error(f"获取付费额度失败: {str(e)}", exc_info=True)
        return 0


# ============================================================
# 额度增加（购买/充值）
# ============================================================

async def add_credits(
    user_id: int,
    amount: int,
    db: Session,
    description: Optional[str] = None,
    transaction_type: str = "purchase"
) -> bool:
    """
    为用户增加额度（购买或管理员充值）
    """
    try:
        if amount <= 0:
            raise ValueError("增加额度必须大于0")

        # 创建交易记录
        transaction = CreditTransaction(
            user_id=user_id,
            amount=amount,
            transaction_type=transaction_type,
            description=description or f"购买 {amount} 次诊断额度",
            status="completed",
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=CREDIT_EXPIRY_DAYS)
        )
        db.add(transaction)

        # 更新用户余额
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.credit_balance = (user.credit_balance or 0) + amount
            user.updated_at = datetime.now()

        db.commit()
        logger.info(f"用户 {user_id} 增加 {amount} 次额度，类型: {transaction_type}")
        return True

    except Exception as e:
        db.rollback()
        logger.error(f"增加额度失败: {str(e)}", exc_info=True)
        return False


# ============================================================
# 额度过期处理
# ============================================================

async def expire_old_credits(db: Session) -> int:
    """
    处理过期额度
    返回处理的过期记录数
    """
    try:
        now = datetime.now()
        
        # 查找过期未使用的额度
        expired_transactions = db.query(CreditTransaction).filter(
            and_(
                CreditTransaction.expires_at.isnot(None),
                CreditTransaction.expires_at < now,
                CreditTransaction.status == "completed",
                CreditTransaction.transaction_type.in_(["purchase", "trial"])
            )
        ).all()

        expired_count = 0
        for transaction in expired_transactions:
            # 标记为已过期
            transaction.status = "expired"
            expired_count += 1

        if expired_count > 0:
            db.commit()
            logger.info(f"已处理 {expired_count} 条过期额度记录")

        return expired_count

    except Exception as e:
        db.rollback()
        logger.error(f"处理过期额度失败: {str(e)}", exc_info=True)
        return 0


# ============================================================
# 诊断可行性检查
# ============================================================

async def can_perform_diagnostic(
    user_id: int,
    diagnostic_type: str,
    db: Session
) -> Tuple[bool, str]:
    """
    检查用户是否可以进行指定类型的诊断
    返回 (是否可行, 提示信息)
    """
    try:
        # 验证诊断类型
        if diagnostic_type not in DIAGNOSTIC_COST:
            return False, f"未知的诊断类型: {diagnostic_type}"

        # 免费诊断检查
        if is_free_diagnostic(diagnostic_type):
            free_remaining = await get_free_daily_credits(user_id, db)
            if free_remaining <= 0:
                return False, "今日免费查询次数已用完，请使用付费诊断或明天再试"
            return True, f"可以进行免费查询，今日剩余 {free_remaining} 次"

        # 付费诊断检查
        paid_balance = await get_paid_credits_balance(user_id, db)
        cost = get_diagnostic_cost(diagnostic_type)
        
        if paid_balance < cost:
            return False, f"付费额度不足，需要 {cost} 次，当前剩余 {paid_balance} 次"
        
        return True, f"可以进行 {diagnostic_type} 诊断，将消耗 {cost} 次额度"

    except Exception as e:
        logger.error(f"诊断可行性检查失败: {str(e)}", exc_info=True)
        return False, "诊断可行性检查失败"


# ============================================================
# 获取用户诊断统计
# ============================================================

async def get_user_diagnostic_stats(user_id: int, db: Session) -> dict:
    """
    获取用户诊断使用统计
    """
    try:
        # 获取各类型诊断使用次数
        stats = {}
        for diag_type in DIAGNOSTIC_COST.keys():
            count = db.query(func.count(CreditTransaction.id)).filter(
                and_(
                    CreditTransaction.user_id == user_id,
                    CreditTransaction.transaction_type == diag_type,
                    CreditTransaction.status == "completed"
                )
            ).scalar() or 0
            stats[diag_type] = count

        # 获取总消耗
        total_cost = db.query(func.sum(func.abs(CreditTransaction.amount))).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(DIAGNOSTIC_TYPES["paid"]),
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0

        return {
            "user_id": user_id,
            "usage_stats": stats,
            "total_paid_usage": total_cost,
            "free_remaining": await get_free_daily_credits(user_id, db),
            "paid_remaining": await get_paid_credits_balance(user_id, db)
        }

    except Exception as e:
        logger.error(f"获取诊断统计失败: {str(e)}", exc_info=True)
        return {}
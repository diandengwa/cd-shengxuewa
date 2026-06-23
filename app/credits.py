#!/usr/bin/env python3
"""
诊断次数管理模块：扣减/增加credits、检查余额、免费额度管理
用于成都K12升学参谋（cd-shengxuewa）付费模式重构 — 按次诊断计费方案
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

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
DIAGNOSTIC_COST = 1  # 每次诊断消耗1次额度

# ============================================================
# 免费额度管理
# ============================================================

async def get_free_daily_credits(user_id: int, db: Session) -> int:
    """
    获取用户每日免费额度
    返回当日剩余免费次数
    """
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # 查询今日已使用的免费额度
        used_today = db.query(func.count(CreditTransaction.id)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type == "free",
                CreditTransaction.created_at >= today_start,
                CreditTransaction.created_at < today_end,
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0

        remaining = max(0, FREE_DAILY_CREDITS - used_today)
        logger.info(f"用户 {user_id} 今日免费额度剩余: {remaining}")
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

        # 获取免费额度
        free_credits = await get_free_daily_credits(user_id, db)

        # 获取付费额度（未过期的）
        now = datetime.now()
        paid_credits = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type == "purchase",
                CreditTransaction.status == "completed",
                CreditTransaction.expires_at > now
            )
        ).scalar() or 0

        # 获取已使用的付费额度
        used_paid = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type == "diagnosis",
                CreditTransaction.status == "completed",
                CreditTransaction.source == "paid"
            )
        ).scalar() or 0

        # 计算可用付费额度
        available_paid = max(0, paid_credits - used_paid)

        # 总余额 = 免费额度 + 可用付费额度
        total_balance = free_credits + available_paid

        logger.info(f"用户 {user_id} 额度检查: 免费={free_credits}, 付费={available_paid}, 总计={total_balance}")

        return CreditBalanceResponse(
            user_id=user_id,
            free_credits=free_credits,
            paid_credits=available_paid,
            total_balance=total_balance,
            daily_limit=FREE_DAILY_CREDITS,
            trial_used=user.trial_used or False
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检查额度失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="检查额度失败"
        )


# ============================================================
# 诊断次数消耗
# ============================================================

async def deduct_credit(
    user_id: int,
    db: Session,
    amount: int = DIAGNOSTIC_COST,
    description: str = "诊断消耗",
    force_paid: bool = False
) -> CreditDeductResponse:
    """
    消耗诊断次数
    优先使用免费额度，不足时使用付费额度
    返回消耗结果
    """
    try:
        # 获取用户信息
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        # 检查可用额度
        balance_check = await check_credit_balance(user_id, db)
        if balance_check.total_balance < amount:
            logger.warning(f"用户 {user_id} 额度不足: 需要{amount}, 可用{balance_check.total_balance}")
            return CreditDeductResponse(
                success=False,
                message="额度不足，请购买诊断次数",
                remaining_credits=balance_check.total_balance,
                transaction_id=None
            )

        # 确定消耗来源
        source = "paid"
        transaction_type = "diagnosis"
        
        if not force_paid and balance_check.free_credits >= amount:
            # 优先使用免费额度
            source = "free"
            transaction_type = "free"
            logger.info(f"用户 {user_id} 使用免费额度消耗 {amount} 次")
        else:
            # 使用付费额度
            logger.info(f"用户 {user_id} 使用付费额度消耗 {amount} 次")

        # 创建消耗记录
        transaction = CreditTransaction(
            user_id=user_id,
            amount=-amount,  # 负数表示消耗
            transaction_type=transaction_type,
            source=source,
            description=description,
            status="completed",
            created_at=datetime.now()
        )
        db.add(transaction)

        # 更新用户余额
        user.credit_balance = (user.credit_balance or 0) - amount
        user.updated_at = datetime.now()

        # 如果是免费额度消耗，更新今日使用计数
        if source == "free":
            user.daily_used = (user.daily_used or 0) + amount

        db.commit()
        db.refresh(transaction)

        # 获取更新后的余额
        new_balance = await check_credit_balance(user_id, db)

        logger.info(f"用户 {user_id} 成功消耗 {amount} 次诊断额度，剩余 {new_balance.total_balance} 次")

        return CreditDeductResponse(
            success=True,
            message=f"成功消耗 {amount} 次诊断额度",
            remaining_credits=new_balance.total_balance,
            transaction_id=transaction.id,
            source=source
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"消耗额度失败: {str(e)}", exc_info=True)
        return CreditDeductResponse(
            success=False,
            message="消耗额度失败，请稍后重试",
            remaining_credits=0,
            transaction_id=None
        )


# ============================================================
# 额度增加（购买/管理员操作）
# ============================================================

async def add_credits(
    user_id: int,
    amount: int,
    db: Session,
    transaction_type: str = "purchase",
    description: str = "购买诊断次数",
    expires_in_days: int = CREDIT_EXPIRY_DAYS
) -> bool:
    """
    为用户增加诊断次数
    支持购买、管理员赠送等操作
    """
    try:
        if amount <= 0:
            logger.error(f"增加额度数量必须为正数: {amount}")
            return False

        # 获取用户
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"用户 {user_id} 不存在")
            return False

        # 计算过期时间
        expires_at = datetime.now() + timedelta(days=expires_in_days) if expires_in_days > 0 else None

        # 创建交易记录
        transaction = CreditTransaction(
            user_id=user_id,
            amount=amount,
            transaction_type=transaction_type,
            description=description,
            status="completed",
            created_at=datetime.now(),
            expires_at=expires_at
        )
        db.add(transaction)

        # 更新用户余额
        user.credit_balance = (user.credit_balance or 0) + amount
        user.updated_at = datetime.now()

        db.commit()
        logger.info(f"用户 {user_id} 成功增加 {amount} 次诊断额度（{transaction_type}），有效期至 {expires_at}")
        return True

    except Exception as e:
        db.rollback()
        logger.error(f"增加额度失败: {str(e)}", exc_info=True)
        return False


# ============================================================
# 批量操作与查询
# ============================================================

async def get_credit_history(
    user_id: int,
    db: Session,
    limit: int = 50,
    offset: int = 0
) -> list:
    """
    获取用户额度使用历史
    """
    try:
        transactions = db.query(CreditTransaction).filter(
            CreditTransaction.user_id == user_id
        ).order_by(
            CreditTransaction.created_at.desc()
        ).offset(offset).limit(limit).all()

        return [
            {
                "id": t.id,
                "amount": t.amount,
                "type": t.transaction_type,
                "source": t.source,
                "description": t.description,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None
            }
            for t in transactions
        ]

    except Exception as e:
        logger.error(f"获取额度历史失败: {str(e)}", exc_info=True)
        return []


async def check_daily_limit(user_id: int, db: Session) -> Tuple[bool, int]:
    """
    检查用户是否达到每日免费额度上限
    返回 (是否可继续使用, 剩余次数)
    """
    try:
        remaining = await get_free_daily_credits(user_id, db)
        return remaining > 0, remaining

    except Exception as e:
        logger.error(f"检查每日限额失败: {str(e)}", exc_info=True)
        return False, 0


async def reset_daily_credits(db: Session) -> int:
    """
    重置所有用户的每日免费额度使用计数
    通常在每日凌晨执行
    返回重置的用户数
    """
    try:
        # 重置所有用户的每日使用计数
        reset_count = db.query(User).update(
            {"daily_used": 0, "updated_at": datetime.now()}
        )
        db.commit()
        logger.info(f"成功重置 {reset_count} 个用户的每日免费额度")
        return reset_count

    except Exception as e:
        db.rollback()
        logger.error(f"重置每日额度失败: {str(e)}", exc_info=True)
        return 0
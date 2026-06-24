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
                CreditTransaction.transaction_type.in_(["purchase", "admin_add"]),
                CreditTransaction.status == "completed",
                CreditTransaction.expires_at > now
            )
        ).scalar() or 0

        # 总余额 = 免费额度 + 付费额度
        total_balance = free_credits + paid_credits

        return CreditBalanceResponse(
            user_id=user_id,
            free_credits=free_credits,
            paid_credits=paid_credits,
            total_balance=total_balance,
            daily_limit=FREE_DAILY_CREDITS
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
# 诊断次数管理（新增核心功能）
# ============================================================

async def check_credits(user_id: int, db: Session) -> Tuple[bool, int, str]:
    """
    检查用户是否有足够的诊断次数
    返回: (是否有足够次数, 可用次数, 消息)
    """
    try:
        # 获取用户信息
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False, 0, "用户不存在"

        # 获取免费额度
        free_credits = await get_free_daily_credits(user_id, db)

        # 获取付费额度（未过期的）
        now = datetime.now()
        paid_credits = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["purchase", "admin_add"]),
                CreditTransaction.status == "completed",
                CreditTransaction.expires_at > now
            )
        ).scalar() or 0

        total_credits = free_credits + paid_credits

        if total_credits >= DIAGNOSTIC_COST:
            return True, total_credits, f"可用次数: {total_credits} (免费: {free_credits}, 付费: {paid_credits})"
        else:
            return False, total_credits, f"次数不足，需要 {DIAGNOSTIC_COST} 次，当前可用 {total_credits} 次"

    except Exception as e:
        logger.error(f"检查诊断次数失败: {str(e)}", exc_info=True)
        return False, 0, "检查诊断次数失败"


async def consume_credits(user_id: int, db: Session) -> Tuple[bool, str]:
    """
    消耗一次诊断次数
    优先消耗免费额度，再消耗付费额度
    返回: (是否成功, 消息)
    """
    try:
        # 检查用户是否存在
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False, "用户不存在"

        # 检查是否有可用次数
        has_credits, available, msg = await check_credits(user_id, db)
        if not has_credits:
            return False, f"诊断次数不足: {msg}"

        # 获取今日已使用的免费额度
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        used_free_today = db.query(func.count(CreditTransaction.id)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type == "free",
                CreditTransaction.created_at >= today_start,
                CreditTransaction.created_at < today_end,
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0

        # 优先使用免费额度
        if used_free_today < FREE_DAILY_CREDITS:
            # 使用免费额度
            transaction = CreditTransaction(
                user_id=user_id,
                amount=-DIAGNOSTIC_COST,
                transaction_type="free",
                description="免费诊断消耗",
                status="completed",
                created_at=datetime.now(),
                expires_at=None
            )
            db.add(transaction)
            logger.info(f"用户 {user_id} 使用免费额度进行诊断")
        else:
            # 使用付费额度
            # 查找最早过期的付费额度进行消耗
            paid_transaction = db.query(CreditTransaction).filter(
                and_(
                    CreditTransaction.user_id == user_id,
                    CreditTransaction.transaction_type.in_(["purchase", "admin_add"]),
                    CreditTransaction.status == "completed",
                    CreditTransaction.expires_at > datetime.now(),
                    CreditTransaction.amount > 0
                )
            ).order_by(CreditTransaction.expires_at.asc()).first()

            if not paid_transaction:
                return False, "无可用的付费额度"

            # 创建消耗记录
            transaction = CreditTransaction(
                user_id=user_id,
                amount=-DIAGNOSTIC_COST,
                transaction_type="diagnostic",
                description="付费诊断消耗",
                status="completed",
                created_at=datetime.now(),
                expires_at=None
            )
            db.add(transaction)

            # 更新付费额度记录（减少可用次数）
            paid_transaction.amount -= DIAGNOSTIC_COST
            if paid_transaction.amount <= 0:
                paid_transaction.status = "expired"

            logger.info(f"用户 {user_id} 使用付费额度进行诊断")

        # 更新用户总余额
        user.credit_balance = (user.credit_balance or 0) - DIAGNOSTIC_COST
        user.updated_at = datetime.now()

        db.commit()
        return True, "诊断次数消耗成功"

    except Exception as e:
        db.rollback()
        logger.error(f"消耗诊断次数失败: {str(e)}", exc_info=True)
        return False, f"消耗诊断次数失败: {str(e)}"


async def add_credits(user_id: int, amount: int, db: Session, 
                      transaction_type: str = "admin_add", 
                      description: str = "管理员手动增加") -> Tuple[bool, str]:
    """
    为用户增加诊断次数
    支持管理员手动增加和购买增加
    返回: (是否成功, 消息)
    """
    try:
        if amount <= 0:
            return False, "增加次数必须大于0"

        # 检查用户是否存在
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False, "用户不存在"

        # 创建增加记录
        transaction = CreditTransaction(
            user_id=user_id,
            amount=amount,
            transaction_type=transaction_type,
            description=description,
            status="completed",
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=CREDIT_EXPIRY_DAYS)
        )
        db.add(transaction)

        # 更新用户余额
        user.credit_balance = (user.credit_balance or 0) + amount
        user.updated_at = datetime.now()

        db.commit()
        logger.info(f"用户 {user_id} 增加 {amount} 次诊断次数，类型: {transaction_type}")
        return True, f"成功增加 {amount} 次诊断次数"

    except Exception as e:
        db.rollback()
        logger.error(f"增加诊断次数失败: {str(e)}", exc_info=True)
        return False, f"增加诊断次数失败: {str(e)}"


# ============================================================
# 诊断次数查询接口（兼容旧版）
# ============================================================

async def get_credit_summary(user_id: int, db: Session) -> dict:
    """
    获取用户诊断次数汇总信息
    返回包含免费额度、付费额度、过期额度等详细信息
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        now = datetime.now()

        # 免费额度
        free_credits = await get_free_daily_credits(user_id, db)

        # 有效付费额度
        paid_credits = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["purchase", "admin_add"]),
                CreditTransaction.status == "completed",
                CreditTransaction.expires_at > now
            )
        ).scalar() or 0

        # 已过期额度
        expired_credits = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["purchase", "admin_add"]),
                CreditTransaction.status == "completed",
                CreditTransaction.expires_at <= now
            )
        ).scalar() or 0

        # 总消耗次数
        total_consumed = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["free", "diagnostic"]),
                CreditTransaction.status == "completed",
                CreditTransaction.amount < 0
            )
        ).scalar() or 0

        return {
            "user_id": user_id,
            "free_credits": free_credits,
            "paid_credits": paid_credits,
            "expired_credits": expired_credits,
            "total_consumed": abs(total_consumed),
            "total_balance": free_credits + paid_credits,
            "daily_limit": FREE_DAILY_CREDITS
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取诊断次数汇总失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取诊断次数汇总失败"
        )
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

        total_credits = free_credits + paid_credits

        return CreditBalanceResponse(
            user_id=user_id,
            free_credits=free_credits,
            paid_credits=paid_credits,
            total_credits=total_credits,
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
# 诊断次数检查（新增）
# ============================================================

async def check_diagnosis_credits(user_id: int, db: Session) -> Tuple[bool, str, int]:
    """
    检查用户是否有足够的诊断次数
    返回: (是否有足够次数, 提示信息, 可用次数)
    """
    try:
        # 获取用户信息
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False, "用户不存在", 0

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
            return True, "额度充足", total_credits
        else:
            return False, f"额度不足，当前可用 {total_credits} 次，每次诊断需 {DIAGNOSTIC_COST} 次", total_credits

    except Exception as e:
        logger.error(f"检查诊断次数失败: {str(e)}", exc_info=True)
        return False, "检查额度失败", 0


# ============================================================
# 诊断次数消耗（新增）
# ============================================================

async def consume_diagnosis_credit(user_id: int, db: Session, description: str = "诊断消耗") -> Tuple[bool, str]:
    """
    消耗一次诊断次数
    优先使用免费额度，再使用付费额度
    返回: (是否成功, 提示信息)
    """
    try:
        # 检查用户是否存在
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False, "用户不存在"

        # 检查是否有足够额度
        has_credits, message, _ = await check_diagnosis_credits(user_id, db)
        if not has_credits:
            return False, message

        # 获取今日免费额度
        free_credits = await get_free_daily_credits(user_id, db)

        # 优先使用免费额度
        if free_credits >= DIAGNOSTIC_COST:
            # 使用免费额度
            transaction = CreditTransaction(
                user_id=user_id,
                amount=-DIAGNOSTIC_COST,
                transaction_type="free",
                description=description,
                status="completed",
                created_at=datetime.now()
            )
            db.add(transaction)
            logger.info(f"用户 {user_id} 使用免费额度消耗 {DIAGNOSTIC_COST} 次诊断")
        else:
            # 使用付费额度
            transaction = CreditTransaction(
                user_id=user_id,
                amount=-DIAGNOSTIC_COST,
                transaction_type="paid",
                description=description,
                status="completed",
                created_at=datetime.now()
            )
            db.add(transaction)

            # 更新用户付费额度余额
            user.credit_balance = max(0, (user.credit_balance or 0) - DIAGNOSTIC_COST)
            user.updated_at = datetime.now()

            logger.info(f"用户 {user_id} 使用付费额度消耗 {DIAGNOSTIC_COST} 次诊断")

        db.commit()
        return True, "诊断次数消耗成功"

    except Exception as e:
        db.rollback()
        logger.error(f"消耗诊断次数失败: {str(e)}", exc_info=True)
        return False, f"消耗诊断次数失败: {str(e)}"


# ============================================================
# 增加诊断次数（新增）
# ============================================================

async def add_diagnosis_credits(
    user_id: int,
    amount: int,
    db: Session,
    transaction_type: str = "admin_add",
    description: str = "管理员增加额度",
    expires_in_days: Optional[int] = None
) -> Tuple[bool, str]:
    """
    为用户增加诊断次数
    支持管理员手动增加、购买增加等场景
    返回: (是否成功, 提示信息)
    """
    try:
        if amount <= 0:
            return False, "增加次数必须大于0"

        # 检查用户是否存在
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False, "用户不存在"

        # 计算过期时间
        if expires_in_days is None:
            expires_in_days = CREDIT_EXPIRY_DAYS
        expires_at = datetime.now() + timedelta(days=expires_in_days)

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

        # 更新用户额度
        user.credit_balance = (user.credit_balance or 0) + amount
        user.updated_at = datetime.now()

        db.commit()
        logger.info(f"用户 {user_id} 增加 {amount} 次诊断额度，过期时间: {expires_at}")
        return True, f"成功增加 {amount} 次诊断额度"

    except Exception as e:
        db.rollback()
        logger.error(f"增加诊断次数失败: {str(e)}", exc_info=True)
        return False, f"增加诊断次数失败: {str(e)}"


# ============================================================
# 获取免费额度剩余（新增）
# ============================================================

async def get_free_query_remaining(user_id: int, db: Session) -> int:
    """
    获取用户今日免费诊断剩余次数
    返回剩余免费次数
    """
    try:
        free_credits = await get_free_daily_credits(user_id, db)
        return free_credits
    except Exception as e:
        logger.error(f"获取免费额度剩余失败: {str(e)}", exc_info=True)
        return 0


# ============================================================
# 诊断次数扣减（兼容旧接口）
# ============================================================

async def deduct_credit(
    user_id: int,
    db: Session,
    request: Optional[CreditDeductRequest] = None
) -> CreditDeductResponse:
    """
    扣减用户诊断次数（兼容旧接口）
    支持指定扣减数量，默认扣减1次
    """
    try:
        deduct_amount = request.amount if request else DIAGNOSTIC_COST
        description = request.description if request and request.description else "诊断消耗"

        success, message = await consume_diagnosis_credit(user_id, db, description)

        if success:
            # 获取最新余额
            balance = await check_credit_balance(user_id, db)
            return CreditDeductResponse(
                success=True,
                message=message,
                remaining_credits=balance.total_credits,
                deducted_amount=deduct_amount
            )
        else:
            return CreditDeductResponse(
                success=False,
                message=message,
                remaining_credits=0,
                deducted_amount=0
            )

    except Exception as e:
        logger.error(f"扣减诊断次数失败: {str(e)}", exc_info=True)
        return CreditDeductResponse(
            success=False,
            message=f"扣减失败: {str(e)}",
            remaining_credits=0,
            deducted_amount=0
        )
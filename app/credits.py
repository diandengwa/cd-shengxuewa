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
                or_(
                    CreditTransaction.expires_at.is_(None),
                    CreditTransaction.expires_at > now
                )
            )
        ).scalar() or 0

        # 获取已消耗的付费额度
        used_paid = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type == "diagnosis",
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0

        # 计算可用付费额度
        available_paid = max(0, paid_credits - used_paid)

        # 总余额 = 免费额度 + 可用付费额度
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
# 额度消耗
# ============================================================

async def deduct_credit(
    user_id: int,
    db: Session,
    diagnosis_type: str = "basic",
    description: Optional[str] = None
) -> CreditDeductResponse:
    """
    消耗用户额度（优先使用免费额度，不足时使用付费额度）
    
    Args:
        user_id: 用户ID
        db: 数据库会话
        diagnosis_type: 诊断类型（basic=基础查询, deep=深度诊断）
        description: 消耗描述
    
    Returns:
        CreditDeductResponse: 消耗结果
    """
    try:
        # 获取用户信息
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        # 确定消耗次数
        cost = DIAGNOSTIC_COST
        if diagnosis_type == "deep":
            cost = 3  # 深度诊断消耗3次额度

        # 检查免费额度
        free_credits = await get_free_daily_credits(user_id, db)
        
        # 检查付费额度
        now = datetime.now()
        paid_credits = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["purchase", "admin_add"]),
                CreditTransaction.status == "completed",
                or_(
                    CreditTransaction.expires_at.is_(None),
                    CreditTransaction.expires_at > now
                )
            )
        ).scalar() or 0
        
        used_paid = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type == "diagnosis",
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0
        
        available_paid = max(0, paid_credits - used_paid)
        
        total_available = free_credits + available_paid
        
        # 检查余额是否充足
        if total_available < cost:
            logger.warning(f"用户 {user_id} 余额不足，需要 {cost}，可用 {total_available}")
            return CreditDeductResponse(
                success=False,
                remaining_credits=total_available,
                deducted_credits=0,
                message=f"额度不足，需要 {cost} 次，当前可用 {total_available} 次"
            )

        # 优先使用免费额度
        deducted_from_free = min(free_credits, cost)
        deducted_from_paid = cost - deducted_from_free
        
        # 记录消耗
        if deducted_from_free > 0:
            free_transaction = CreditTransaction(
                user_id=user_id,
                amount=deducted_from_free,
                transaction_type="free",
                description=description or f"{'深度诊断' if diagnosis_type == 'deep' else '基础查询'}（免费额度）",
                status="completed",
                created_at=datetime.now()
            )
            db.add(free_transaction)
        
        if deducted_from_paid > 0:
            paid_transaction = CreditTransaction(
                user_id=user_id,
                amount=deducted_from_paid,
                transaction_type="diagnosis",
                description=description or f"{'深度诊断' if diagnosis_type == 'deep' else '基础查询'}（付费额度）",
                status="completed",
                created_at=datetime.now()
            )
            db.add(paid_transaction)
        
        # 更新用户余额
        user.credit_balance = max(0, (user.credit_balance or 0) - cost)
        user.updated_at = datetime.now()
        
        db.commit()
        
        # 计算剩余额度
        remaining_free = max(0, free_credits - deducted_from_free)
        remaining_paid = max(0, available_paid - deducted_from_paid)
        remaining_total = remaining_free + remaining_paid
        
        logger.info(f"用户 {user_id} 消耗 {cost} 次额度（免费: {deducted_from_free}, 付费: {deducted_from_paid}），剩余: {remaining_total}")
        
        return CreditDeductResponse(
            success=True,
            remaining_credits=remaining_total,
            deducted_credits=cost,
            message=f"消耗 {cost} 次额度成功，剩余 {remaining_total} 次"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"消耗额度失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="消耗额度失败"
        )


# ============================================================
# 额度充值
# ============================================================

async def add_credits(
    user_id: int,
    amount: int,
    db: Session,
    transaction_type: str = "purchase",
    description: Optional[str] = None,
    expires_in_days: Optional[int] = CREDIT_EXPIRY_DAYS
) -> bool:
    """
    为用户增加额度（充值/管理员添加）
    
    Args:
        user_id: 用户ID
        amount: 增加的数量
        db: 数据库会话
        transaction_type: 交易类型（purchase=购买, admin_add=管理员添加）
        description: 描述
        expires_in_days: 有效期（天），None表示永不过期
    
    Returns:
        bool: 是否成功
    """
    try:
        # 获取用户信息
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="增加数量必须大于0"
            )
        
        # 计算过期时间
        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.now() + timedelta(days=expires_in_days)
        
        # 创建交易记录
        transaction = CreditTransaction(
            user_id=user_id,
            amount=amount,
            transaction_type=transaction_type,
            description=description or f"{'购买' if transaction_type == 'purchase' else '管理员添加'} {amount} 次诊断额度",
            status="completed",
            created_at=datetime.now(),
            expires_at=expires_at
        )
        db.add(transaction)
        
        # 更新用户余额
        user.credit_balance = (user.credit_balance or 0) + amount
        user.updated_at = datetime.now()
        
        db.commit()
        
        logger.info(f"用户 {user_id} 增加 {amount} 次额度（类型: {transaction_type}），过期时间: {expires_at}")
        return True
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"增加额度失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="增加额度失败"
        )


# ============================================================
# 额度查询与统计
# ============================================================

async def get_credit_history(
    user_id: int,
    db: Session,
    limit: int = 20,
    offset: int = 0
) -> list:
    """
    获取用户额度使用历史
    
    Args:
        user_id: 用户ID
        db: 数据库会话
        limit: 返回条数
        offset: 偏移量
    
    Returns:
        list: 交易记录列表
    """
    try:
        transactions = db.query(CreditTransaction).filter(
            CreditTransaction.user_id == user_id
        ).order_by(
            CreditTransaction.created_at.desc()
        ).offset(offset).limit(limit).all()
        
        return transactions
        
    except Exception as e:
        logger.error(f"获取额度历史失败: {str(e)}", exc_info=True)
        return []


async def get_credit_statistics(user_id: int, db: Session) -> dict:
    """
    获取用户额度使用统计
    
    Args:
        user_id: 用户ID
    
    Returns:
        dict: 统计信息
    """
    try:
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # 今日使用
        today_used = db.query(func.count(CreditTransaction.id)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["free", "diagnosis"]),
                CreditTransaction.created_at >= today_start,
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0
        
        # 本月使用
        month_used = db.query(func.count(CreditTransaction.id)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["free", "diagnosis"]),
                CreditTransaction.created_at >= month_start,
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0
        
        # 总购买量
        total_purchased = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type == "purchase",
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0
        
        # 总消耗量
        total_used = db.query(func.sum(CreditTransaction.amount)).filter(
            and_(
                CreditTransaction.user_id == user_id,
                CreditTransaction.transaction_type.in_(["free", "diagnosis"]),
                CreditTransaction.status == "completed"
            )
        ).scalar() or 0
        
        return {
            "today_used": today_used,
            "month_used": month_used,
            "total_purchased": total_purchased,
            "total_used": total_used,
            "daily_limit": FREE_DAILY_CREDITS
        }
        
    except Exception as e:
        logger.error(f"获取额度统计失败: {str(e)}", exc_info=True)
        return {
            "today_used": 0,
            "month_used": 0,
            "total_purchased": 0,
            "total_used": 0,
            "daily_limit": FREE_DAILY_CREDITS
        }


# ============================================================
# 额度检查装饰器/依赖
# ============================================================

async def require_credits(
    user_id: int,
    db: Session = Depends(get_db),
    diagnosis_type: str = "basic"
) -> bool:
    """
    检查用户是否有足够额度进行诊断
    用于FastAPI依赖注入
    
    Args:
        user_id: 用户ID
        db: 数据库会话
        diagnosis_type: 诊断类型
    
    Returns:
        bool: 是否有足够额度
    """
    try:
        balance = await check_credit_balance(user_id, db)
        cost = DIAGNOSTIC_COST if diagnosis_type == "basic" else 3
        
        if balance.total_balance < cost:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"额度不足，需要 {cost} 次，当前可用 {balance.total_balance} 次"
            )
        
        return True
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检查额度失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="检查额度失败"
        )
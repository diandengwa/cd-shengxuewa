"""
配额中间件 v3.0 — 按次诊断计费方案
免费层: 每月3次基础查询 | 深度诊断: 消耗credits (免费用户无, Pro Lite 30 credits/月, Pro Max 无限)
存储: SQLite (users表)
"""

import json
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timedelta
from .models import UserRecord, PlanType, QuotaInfo, FamilyInfo
from .database import get_db, init_db

logger = logging.getLogger("k12_rocket")

# 初始化数据库
init_db()

# 配额常量
FREE_MONTHLY_QUERIES = 3  # 免费用户每月基础查询次数
LITE_MONTHLY_CREDITS = 30  # Pro Lite每月credits数
DIAGNOSE_COST = 1  # 每次深度诊断消耗1 credit


def _get_month_start() -> str:
    """获取本月1号日期"""
    return datetime.now().strftime("%Y-%m-01")


def get_or_create_user(openid: str) -> UserRecord:
    """获取或创建用户"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM users WHERE openid = ?", (openid,))
    row = cursor.fetchone()
    
    if row:
        conn.close()
        # 反序列化
        data = json.loads(row["data"])
        return UserRecord(**data)

    # 新用户
    user = UserRecord(
        openid=openid,
        plan=PlanType.FREE,
        quota=QuotaInfo(
            plan=PlanType.FREE,
            monthly_queries_used=0,
            monthly_queries_reset=_get_month_start(),
            monthly_diagnoses_used=0,
            monthly_diagnoses_reset=_get_month_start(),
            credits_used=0,
            credits_reset=_get_month_start(),
        ),
        family_info=FamilyInfo(),
    )
    
    # 写入数据库
    cursor.execute(
        "INSERT INTO users (openid, data, last_active) VALUES (?, ?, ?)",
        (openid, user.model_dump_json(), user.last_active)
    )
    conn.commit()
    conn.close()
    logger.info(f"[Quota] 新用户注册: {openid[:8]}...")
    return user


def update_user(user: UserRecord):
    """更新用户数据"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO users (openid, data, last_active) VALUES (?, ?, ?)",
        (user.openid, user.model_dump_json(), user.last_active)
    )
    conn.commit()
    conn.close()


def _reset_monthly_quota(user: UserRecord) -> UserRecord:
    """重置月度配额（如果跨月）"""
    month_start = _get_month_start()
    
    # 重置基础查询
    if user.quota.monthly_queries_reset != month_start:
        user.quota.monthly_queries_used = 0
        user.quota.monthly_queries_reset = month_start
    
    # 重置深度诊断
    if user.quota.monthly_diagnoses_reset != month_start:
        user.quota.monthly_diagnoses_used = 0
        user.quota.monthly_diagnoses_reset = month_start
    
    # 重置credits
    if user.quota.credits_reset != month_start:
        user.quota.credits_used = 0
        user.quota.credits_reset = month_start
    
    return user


def get_available_credits(user: UserRecord) -> int:
    """获取用户当前可用credits数"""
    if user.plan == PlanType.MAX:
        return float('inf')
    elif user.plan == PlanType.LITE:
        return LITE_MONTHLY_CREDITS - user.quota.credits_used
    else:
        return 0


def check_quota(openid: str, action: str = "query") -> Tuple[bool, UserRecord, str]:
    """
    检查配额
    action: query(基础查询) | diagnose(深度诊断)
    返回: (allowed, user_record, message)
    """
    try:
        user = get_or_create_user(openid)
        user = _reset_monthly_quota(user)

        if user.plan == PlanType.MAX:
            return True, user, "Pro Max用户，无限使用"

        if action == "query":
            if user.plan == PlanType.FREE:
                if user.quota.monthly_queries_used >= FREE_MONTHLY_QUERIES:
                    remaining = max(0, FREE_MONTHLY_QUERIES - user.quota.monthly_queries_used)
                    msg = (
                        f"免费用户每月{FREE_MONTHLY_QUERIES}次基础查询已用完"
                        f"（本月已用{user.quota.monthly_queries_used}次）。"
                        f"升级Pro Lite ¥29.9/月获取更多次数。"
                    )
                    return False, user, msg
                # 扣配额
                user.quota.monthly_queries_used += 1
                remaining = FREE_MONTHLY_QUERIES - user.quota.monthly_queries_used
                update_user(user)
                return True, user, f"剩余{remaining}次免费基础查询/本月"

            elif user.plan == PlanType.LITE:
                # Pro Lite基础查询无限
                return True, user, "Pro Lite用户，无限基础查询"

        elif action == "diagnose":
            if user.plan == PlanType.FREE:
                msg = (
                    "深度诊断为Pro功能。"
                    f"升级Pro Lite ¥29.9/月获取{LITE_MONTHLY_CREDITS}次/月深度诊断。"
                )
                return False, user, msg

            elif user.plan == PlanType.LITE:
                available_credits = get_available_credits(user)
                if available_credits < DIAGNOSE_COST:
                    msg = (
                        f"Pro Lite每月{LITE_MONTHLY_CREDITS}次深度诊断已用完"
                        f"（本月已用{user.quota.credits_used}次）。"
                        "升级Pro Max ¥99/月获取无限诊断。"
                    )
                    return False, user, msg
                # 消耗credits
                user.quota.credits_used += DIAGNOSE_COST
                user.quota.monthly_diagnoses_used += 1
                remaining_credits = get_available_credits(user)
                update_user(user)
                return True, user, f"剩余{remaining_credits}次深度诊断/本月"

        return True, user, ""

    except Exception as e:
        logger.error(f"[Quota] 检查配额异常: {e}", exc_info=True)
        # 异常时默认允许，避免影响用户体验
        user = get_or_create_user(openid)
        return True, user, "配额检查异常，已临时放行"


def upgrade_plan(openid: str, new_plan: PlanType) -> Optional[UserRecord]:
    """
    升级套餐
    返回升级后的用户对象，失败返回None
    """
    try:
        user = get_or_create_user(openid)
        old_plan = user.plan
        
        # 不允许降级
        if new_plan.value <= old_plan.value:
            logger.warning(f"[Quota] 用户{openid[:8]}尝试降级: {old_plan} -> {new_plan}")
            return None
        
        user.plan = new_plan
        user.quota.plan = new_plan
        
        # 升级时重置配额
        user.quota.monthly_queries_used = 0
        user.quota.monthly_queries_reset = _get_month_start()
        user.quota.monthly_diagnoses_used = 0
        user.quota.monthly_diagnoses_reset = _get_month_start()
        user.quota.credits_used = 0
        user.quota.credits_reset = _get_month_start()
        
        update_user(user)
        logger.info(f"[Quota] 用户{openid[:8]}升级: {old_plan} -> {new_plan}")
        return user
        
    except Exception as e:
        logger.error(f"[Quota] 升级套餐异常: {e}", exc_info=True)
        return None


def get_quota_info(openid: str) -> dict:
    """
    获取用户配额信息（用于前端展示）
    """
    try:
        user = get_or_create_user(openid)
        user = _reset_monthly_quota(user)
        
        info = {
            "plan": user.plan.value,
            "plan_name": user.plan.name,
            "monthly_queries": {
                "total": FREE_MONTHLY_QUERIES if user.plan == PlanType.FREE else "无限",
                "used": user.quota.monthly_queries_used,
                "remaining": max(0, FREE_MONTHLY_QUERIES - user.quota.monthly_queries_used) if user.plan == PlanType.FREE else "无限"
            },
            "monthly_diagnoses": {
                "total": 0 if user.plan == PlanType.FREE else (LITE_MONTHLY_CREDITS if user.plan == PlanType.LITE else "无限"),
                "used": user.quota.monthly_diagnoses_used,
                "remaining": 0 if user.plan == PlanType.FREE else (get_available_credits(user) if user.plan == PlanType.LITE else "无限")
            },
            "credits": {
                "total": 0 if user.plan == PlanType.FREE else (LITE_MONTHLY_CREDITS if user.plan == PlanType.LITE else "无限"),
                "used": user.quota.credits_used,
                "remaining": 0 if user.plan == PlanType.FREE else (get_available_credits(user) if user.plan == PlanType.LITE else "无限")
            },
            "reset_date": user.quota.credits_reset
        }
        
        return info
        
    except Exception as e:
        logger.error(f"[Quota] 获取配额信息异常: {e}", exc_info=True)
        return {
            "plan": "free",
            "plan_name": "免费",
            "error": "获取配额信息失败"
        }


def consume_credits(openid: str, amount: int = 1) -> Tuple[bool, str]:
    """
    消耗用户credits（供其他功能调用）
    返回: (success, message)
    """
    try:
        user = get_or_create_user(openid)
        user = _reset_monthly_quota(user)
        
        if user.plan == PlanType.MAX:
            return True, "Pro Max用户，无限使用"
        
        if user.plan == PlanType.FREE:
            return False, "免费用户无credits，请升级套餐"
        
        available = get_available_credits(user)
        if available < amount:
            return False, f"credits不足（剩余{available}，需要{amount}）"
        
        user.quota.credits_used += amount
        update_user(user)
        
        remaining = get_available_credits(user)
        return True, f"消耗{amount}credits成功，剩余{remaining}"
        
    except Exception as e:
        logger.error(f"[Quota] 消耗credits异常: {e}", exc_info=True)
        return False, "消耗credits失败"
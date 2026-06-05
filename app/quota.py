"""
配额中间件 v2.0
免费层: 5次/周 | Pro Lite: 3次深诊/月+无限问答 | Pro Max: 无限
存储: data/users.json
"""

import json
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timedelta
from .models import UserRecord, PlanType, QuotaInfo, FamilyInfo

logger = logging.getLogger("k12_rocket")

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
USERS_FILE = DATA_DIR / "users.json"


def _load_users() -> dict:
    """加载用户数据"""
    if not USERS_FILE.exists():
        return {}
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_users(users: dict):
    """保存用户数据"""
    USERS_FILE.parent.mkdir(exist_ok=True)
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _get_week_start() -> str:
    """获取本周一日期"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")


def _get_month_start() -> str:
    """获取本月1号日期"""
    return datetime.now().strftime("%Y-%m-01")


def get_or_create_user(openid: str) -> UserRecord:
    """获取或创建用户"""
    users = _load_users()
    if openid in users:
        data = users[openid]
        return UserRecord(**data)

    # 新用户
    user = UserRecord(
        openid=openid,
        plan=PlanType.FREE,
        quota=QuotaInfo(
            plan=PlanType.FREE,
            weekly_queries_used=0,
            weekly_queries_reset=_get_week_start(),
            monthly_diagnoses_used=0,
            monthly_diagnoses_reset=_get_month_start(),
        ),
        family_info=FamilyInfo(),
    )
    users[openid] = user.model_dump()
    _save_users(users)
    logger.info(f"[Quota] 新用户注册: {openid[:8]}...")
    return user


def update_user(user: UserRecord):
    """更新用户数据"""
    users = _load_users()
    users[user.openid] = user.model_dump()
    _save_users(users)


def check_quota(openid: str, action: str = "query") -> Tuple[bool, UserRecord, str]:
    """
    检查配额
    action: query(普通查询) | diagnose(深度诊断)
    返回: (allowed, user_record, message)
    """
    user = get_or_create_user(openid)

    # 重置检查
    week_start = _get_week_start()
    if user.quota.weekly_queries_reset != week_start:
        user.quota.weekly_queries_used = 0
        user.quota.weekly_queries_reset = week_start

    month_start = _get_month_start()
    if user.quota.monthly_diagnoses_reset != month_start:
        user.quota.monthly_diagnoses_used = 0
        user.quota.monthly_diagnoses_reset = month_start

    if user.plan == PlanType.MAX:
        return True, user, "Pro Max用户，无限使用"

    if action == "query":
        if user.plan == PlanType.FREE:
            if user.quota.weekly_queries_used >= 5:
                msg = f"免费用户每周5次查询已用完（本周已用{user.quota.weekly_queries_used}次）。升级Pro Lite ¥29.9/月获取更多次数。"
                return False, user, msg
            # 扣配额
            user.quota.weekly_queries_used += 1
            remaining = 5 - user.quota.weekly_queries_used
            update_user(user)
            return True, user, f"剩余{remaining}次免费查询/本周"

        elif user.plan == PlanType.LITE:
            # Lite无限问答
            return True, user, "Pro Lite用户，无限问答"

    elif action == "diagnose":
        if user.plan == PlanType.FREE:
            msg = "深度诊断为Pro功能。升级Pro Lite ¥29.9/月获取3次/月深度诊断。"
            return False, user, msg

        elif user.plan == PlanType.LITE:
            if user.quota.monthly_diagnoses_used >= 30:
                msg = f"Pro Lite每月30次深度诊断已用完。升级Pro Max ¥99/月获取无限诊断。"
                return False, user, msg
            user.quota.monthly_diagnoses_used += 1
            remaining = 3 - user.quota.monthly_diagnoses_used
            update_user(user)
            return True, user, f"剩余{remaining}次深度诊断/本月"

    return True, user, ""


def upgrade_plan(openid: str, new_plan: PlanType) -> UserRecord:
    """升级套餐"""
    user = get_or_create_user(openid)
    old_plan = user.plan
    user.plan = new_plan
    user.quota.plan = new_plan
    update_user(user)
    logger.info(f"[Quota] 用户 {openid[:8]}... 升级: {old_plan} → {new_plan}")
    return user


def update_family_info(openid: str, family_info: FamilyInfo) -> UserRecord:
    """更新家庭画像"""
    user = get_or_create_user(openid)
    user.family_info = family_info
    update_user(user)
    return user

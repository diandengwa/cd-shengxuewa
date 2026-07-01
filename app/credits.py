#!/usr/bin/env python3
"""
Credits Core Module (Bridged to SQLite payment module)
Allows quota and diagnosis deduction without SQLAlchemy ORM models.
"""

import logging
from typing import Tuple, Optional

logger = logging.getLogger("k12_rocket.credits")

async def check_credits(user_id: str, required: int = 1) -> Tuple[bool, str]:
    """验证用户诊断额度是否足够"""
    try:
        from app.routers.payment import get_user_diagnoses
        user_data = get_user_diagnoses(user_id)
        if not user_data:
            return False, "用户未购买诊断套餐，请先购买。"
            
        if user_data.get("is_unlimited"):
            return True, "额度充足(无限套餐)"
            
        remaining = user_data.get("diagnoses_remaining", 0)
        if remaining >= required:
            return True, "额度充足"
        else:
            return False, f"您的诊断额度不足（剩余 {remaining} 次，本次需要 {required} 次），请充值或购买。"
    except Exception as e:
        logger.error(f"[Credits] check_credits error: {e}", exc_info=True)
        return False, f"额度校验失败: {e}"

async def deduct_credit(user_id: str, amount: int = 1, description: str = "") -> Tuple[bool, str]:
    """扣减用户诊断额度"""
    try:
        from app.routers.payment import deduct_diagnosis, get_user_diagnoses
        if amount == 1:
            success = deduct_diagnosis(user_id)
            if success:
                return True, "扣减成功"
            else:
                return False, "诊断额度不足或用户不存在"
        else:
            from app.routers.payment import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            user_data = get_user_diagnoses(user_id)
            if not user_data:
                conn.close()
                return False, "用户不存在"
                
            if user_data["is_unlimited"]:
                cursor.execute("""
                    UPDATE user_diagnoses 
                    SET diagnoses_used = diagnoses_used + ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (amount, user_id))
                
                cursor.execute("""
                    INSERT INTO diagnosis_usage (user_id, diagnoses_used, usage_type)
                    VALUES (?, ?, 'diagnosis')
                """, (user_id, amount))
                
                conn.commit()
                conn.close()
                return True, "扣减成功"
                
            if user_data["diagnoses_remaining"] >= amount:
                cursor.execute("""
                    UPDATE user_diagnoses 
                    SET diagnoses_used = diagnoses_used + ?,
                        diagnoses_remaining = diagnoses_remaining - ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (amount, amount, user_id))
                
                cursor.execute("""
                    INSERT INTO diagnosis_usage (user_id, diagnoses_used, usage_type)
                    VALUES (?, ?, 'diagnosis')
                """, (user_id, amount))
                
                conn.commit()
                conn.close()
                return True, "扣减成功"
                
            conn.close()
            return False, "诊断额度不足"
    except Exception as e:
        logger.error(f"[Credits] deduct_credit error: {e}", exc_info=True)
        return False, f"扣减失败: {e}"

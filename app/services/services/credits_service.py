#!/usr/bin/env python3
"""
诊断次数管理服务：查询余额、消耗、充值、免费额度检查
K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋
付费模式重构 — 按次诊断计费方案
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ============================================================
# 日志配置
# ============================================================
logger = logging.getLogger("credits_service")

# ============================================================
# 数据库连接（SQLite）
# ============================================================
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("K12_DB_PATH", str(PROJECT_ROOT / "data" / "k12.db"))

@contextmanager
def get_db_connection():
    """获取数据库连接上下文管理器"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"数据库连接错误: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

# ============================================================
# 常量定义
# ============================================================
# 免费诊断次数（新用户注册赠送）
FREE_DIAGNOSES_DEFAULT = 3

# 单次诊断消耗的配额
DIAGNOSIS_COST = 1

# 充值套餐定义（次数, 价格, 有效期天数）
RECHARGE_PLANS = {
    "basic": {"credits": 10, "price": 29.9, "valid_days": 180},
    "standard": {"credits": 30, "price": 69.9, "valid_days": 365},
    "premium": {"credits": 100, "price": 199.9, "valid_days": 730},
}

# ============================================================
# 核心服务类
# ============================================================
class CreditsService:
    """诊断次数管理服务"""

    def __init__(self):
        """初始化服务"""
        self._init_database()

    def _init_database(self):
        """初始化数据库表结构"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 用户配额表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_credits (
                        user_id TEXT PRIMARY KEY,
                        total_credits INTEGER NOT NULL DEFAULT 0,
                        used_credits INTEGER NOT NULL DEFAULT 0,
                        free_credits INTEGER NOT NULL DEFAULT 0,
                        free_used INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # 充值记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS recharge_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        plan_type TEXT NOT NULL,
                        credits INTEGER NOT NULL,
                        amount REAL NOT NULL,
                        valid_days INTEGER NOT NULL,
                        expires_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'completed'
                    )
                """)
                
                # 诊断消耗记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS diagnosis_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        diagnosis_type TEXT NOT NULL,
                        credits_used INTEGER NOT NULL DEFAULT 1,
                        is_free INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        remark TEXT
                    )
                """)
                
                # 创建索引
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_user_credits_user_id 
                    ON user_credits(user_id)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_recharge_user_id 
                    ON recharge_records(user_id)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_diagnosis_user_id 
                    ON diagnosis_logs(user_id)
                """)
                
                logger.info("数据库表初始化完成")
                
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise

    def get_user_credits(self, user_id: str) -> Dict[str, Any]:
        """
        查询用户诊断次数余额
        
        Args:
            user_id: 用户ID
            
        Returns:
            dict: 包含余额信息的字典
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 查询用户配额
                cursor.execute(
                    "SELECT * FROM user_credits WHERE user_id = ?",
                    (user_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    # 新用户，初始化免费额度
                    return self._init_new_user(user_id)
                
                # 计算可用余额
                total_credits = row["total_credits"]
                used_credits = row["used_credits"]
                free_credits = row["free_credits"]
                free_used = row["free_used"]
                
                # 计算可用免费次数
                available_free = max(0, free_credits - free_used)
                
                # 计算可用付费次数
                available_paid = max(0, total_credits - used_credits)
                
                # 总可用次数
                total_available = available_free + available_paid
                
                return {
                    "user_id": user_id,
                    "total_credits": total_credits,
                    "used_credits": used_credits,
                    "available_paid": available_paid,
                    "free_credits": free_credits,
                    "free_used": free_used,
                    "available_free": available_free,
                    "total_available": total_available,
                    "has_credits": total_available > 0,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
                
        except Exception as e:
            logger.error(f"查询用户余额失败: user_id={user_id}, error={e}")
            raise

    def _init_new_user(self, user_id: str) -> Dict[str, Any]:
        """
        初始化新用户免费额度
        
        Args:
            user_id: 用户ID
            
        Returns:
            dict: 初始化后的余额信息
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 插入新用户记录
                cursor.execute("""
                    INSERT INTO user_credits (user_id, total_credits, used_credits, free_credits, free_used)
                    VALUES (?, 0, 0, ?, 0)
                """, (user_id, FREE_DIAGNOSES_DEFAULT))
                
                logger.info(f"新用户初始化成功: user_id={user_id}, free_credits={FREE_DIAGNOSES_DEFAULT}")
                
                return {
                    "user_id": user_id,
                    "total_credits": 0,
                    "used_credits": 0,
                    "available_paid": 0,
                    "free_credits": FREE_DIAGNOSES_DEFAULT,
                    "free_used": 0,
                    "available_free": FREE_DIAGNOSES_DEFAULT,
                    "total_available": FREE_DIAGNOSES_DEFAULT,
                    "has_credits": True,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"初始化新用户失败: user_id={user_id}, error={e}")
            raise

    def consume_diagnosis(self, user_id: str, diagnosis_type: str = "general") -> Tuple[bool, str]:
        """
        消耗一次诊断次数
        
        Args:
            user_id: 用户ID
            diagnosis_type: 诊断类型
            
        Returns:
            tuple: (是否成功, 消息)
        """
        try:
            # 先检查用户余额
            credits_info = self.get_user_credits(user_id)
            
            if not credits_info["has_credits"]:
                return False, "诊断次数不足，请充值"
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 优先使用免费次数
                if credits_info["available_free"] > 0:
                    # 消耗免费次数
                    cursor.execute("""
                        UPDATE user_credits 
                        SET free_used = free_used + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = ?
                    """, (user_id,))
                    
                    # 记录诊断日志
                    cursor.execute("""
                        INSERT INTO diagnosis_logs (user_id, diagnosis_type, credits_used, is_free, remark)
                        VALUES (?, ?, 1, 1, '使用免费诊断次数')
                    """, (user_id, diagnosis_type))
                    
                    logger.info(f"用户 {user_id} 使用免费诊断次数，类型: {diagnosis_type}")
                    return True, "诊断成功（免费次数）"
                    
                else:
                    # 消耗付费次数
                    cursor.execute("""
                        UPDATE user_credits 
                        SET used_credits = used_credits + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND (total_credits - used_credits) > 0
                    """, (user_id,))
                    
                    if cursor.rowcount == 0:
                        return False, "付费次数不足"
                    
                    # 记录诊断日志
                    cursor.execute("""
                        INSERT INTO diagnosis_logs (user_id, diagnosis_type, credits_used, is_free, remark)
                        VALUES (?, ?, 1, 0, '使用付费诊断次数')
                    """, (user_id, diagnosis_type))
                    
                    logger.info(f"用户 {user_id} 使用付费诊断次数，类型: {diagnosis_type}")
                    return True, "诊断成功（付费次数）"
                    
        except Exception as e:
            logger.error(f"消耗诊断次数失败: user_id={user_id}, error={e}")
            return False, f"系统错误: {str(e)}"

    def recharge_credits(self, user_id: str, plan_type: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        用户充值诊断次数
        
        Args:
            user_id: 用户ID
            plan_type: 套餐类型 (basic/standard/premium)
            
        Returns:
            tuple: (是否成功, 消息, 充值详情)
        """
        try:
            # 验证套餐类型
            if plan_type not in RECHARGE_PLANS:
                return False, f"无效的套餐类型: {plan_type}", None
            
            plan = RECHARGE_PLANS[plan_type]
            credits = plan["credits"]
            amount = plan["price"]
            valid_days = plan["valid_days"]
            
            # 计算过期时间
            expires_at = datetime.now() + timedelta(days=valid_days)
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 更新用户总次数
                cursor.execute("""
                    UPDATE user_credits 
                    SET total_credits = total_credits + ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (credits, user_id))
                
                if cursor.rowcount == 0:
                    # 用户不存在，先创建
                    cursor.execute("""
                        INSERT INTO user_credits (user_id, total_credits, free_credits, free_used)
                        VALUES (?, ?, 0, 0)
                    """, (user_id, credits))
                
                # 记录充值记录
                cursor.execute("""
                    INSERT INTO recharge_records (user_id, plan_type, credits, amount, valid_days, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, plan_type, credits, amount, valid_days, expires_at))
                
                recharge_id = cursor.lastrowid
                
                recharge_info = {
                    "recharge_id": recharge_id,
                    "user_id": user_id,
                    "plan_type": plan_type,
                    "credits": credits,
                    "amount": amount,
                    "valid_days": valid_days,
                    "expires_at": expires_at.isoformat(),
                    "created_at": datetime.now().isoformat()
                }
                
                logger.info(f"用户 {user_id} 充值成功: plan={plan_type}, credits={credits}")
                return True, "充值成功", recharge_info
                
        except Exception as e:
            logger.error(f"充值失败: user_id={user_id}, plan={plan_type}, error={e}")
            return False, f"充值失败: {str(e)}", None

    def check_free_credits(self, user_id: str) -> Dict[str, Any]:
        """
        检查用户免费额度
        
        Args:
            user_id: 用户ID
            
        Returns:
            dict: 免费额度信息
        """
        try:
            credits_info = self.get_user_credits(user_id)
            
            return {
                "user_id": user_id,
                "free_total": credits_info["free_credits"],
                "free_used": credits_info["free_used"],
                "free_remaining": credits_info["available_free"],
                "has_free_credits": credits_info["available_free"] > 0
            }
            
        except Exception as e:
            logger.error(f"检查免费额度失败: user_id={user_id}, error={e}")
            raise

    def get_consumption_history(self, user_id: str, limit: int = 20) -> list:
        """
        获取用户诊断消耗历史
        
        Args:
            user_id: 用户ID
            limit: 返回记录数
            
        Returns:
            list: 消耗记录列表
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM diagnosis_logs 
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (user_id, limit))
                
                rows = cursor.fetchall()
                
                history = []
                for row in rows:
                    history.append({
                        "id": row["id"],
                        "user_id": row["user_id"],
                        "diagnosis_type": row["diagnosis_type"],
                        "credits_used": row["credits_used"],
                        "is_free": bool(row["is_free"]),
                        "created_at": row["created_at"],
                        "remark": row["remark"]
                    })
                
                return history
                
        except Exception as e:
            logger.error(f"查询消耗历史失败: user_id={user_id}, error={e}")
            raise

    def get_recharge_history(self, user_id: str, limit: int = 20) -> list:
        """
        获取用户充值历史
        
        Args:
            user_id: 用户ID
            limit: 返回记录数
            
        Returns:
            list: 充值记录列表
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM recharge_records 
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (user_id, limit))
                
                rows = cursor.fetchall()
                
                history = []
                for row in rows:
                    history.append({
                        "id": row["id"],
                        "user_id": row["user_id"],
                        "plan_type": row["plan_type"],
                        "credits": row["credits"],
                        "amount": row["amount"],
                        "valid_days": row["valid_days"],
                        "expires_at": row["expires_at"],
                        "created_at": row["created_at"],
                        "status": row["status"]
                    })
                
                return history
                
        except Exception as e:
            logger.error(f"查询充值历史失败: user_id={user_id}, error={e}")
            raise

    def get_available_plans(self) -> Dict[str, Any]:
        """
        获取可用充值套餐列表
        
        Returns:
            dict: 套餐信息
        """
        return {
            "plans": RECHARGE_PLANS,
            "diagnosis_cost": DIAGNOSIS_COST,
            "free_diagnoses": FREE_DIAGNOSES_DEFAULT
        }

    def reset_free_credits(self, user_id: str) -> bool:
        """
        重置用户免费额度（管理员功能）
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否成功
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE user_credits 
                    SET free_used = 0,
                        free_credits = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (FREE_DIAGNOSES_DEFAULT, user_id))
                
                if cursor.rowcount == 0:
                    # 用户不存在，创建新记录
                    cursor.execute("""
                        INSERT INTO user_credits (user_id, total_credits, used_credits, free_credits, free_used)
                        VALUES (?, 0, 0, ?, 0)
                    """, (user_id, FREE_DIAGNOSES_DEFAULT))
                
                logger.info(f"用户 {user_id} 免费额度已重置为 {FREE_DIAGNOSES_DEFAULT}")
                return True
                
        except Exception as e:
            logger.error(f"重置免费额度失败: user_id={user_id}, error={e}")
            return False


# ============================================================
# 全局单例
# ============================================================
credits_service = CreditsService()


# ============================================================
# 便捷函数（供外部调用）
# ============================================================
def get_user_credits(user_id: str) -> Dict[str, Any]:
    """查询用户诊断次数余额"""
    return credits_service.get_user_credits(user_id)

def consume_diagnosis(user_id: str, diagnosis_type: str = "general") -> Tuple[bool, str]:
    """消耗一次诊断次数"""
    return credits_service.consume_diagnosis(user_id, diagnosis_type)

def recharge_credits(user_id: str, plan_type: str) -> Tuple[bool, str, Optional[Dict]]:
    """用户充值诊断次数"""
    return credits_service.recharge_credits(user_id, plan_type)

def check_free_credits(user_id: str) -> Dict[str, Any]:
    """检查用户免费额度"""
    return credits_service.check_free_credits(user_id)

def get_consumption_history(user_id: str, limit: int = 20) -> list:
    """获取用户诊断消耗历史"""
    return credits_service.get_consumption_history(user_id, limit)

def get_recharge_history(user_id: str, limit: int = 20) -> list:
    """获取用户充值历史"""
    return credits_service.get_recharge_history(user_id, limit)

def get_available_plans() -> Dict[str, Any]:
    """获取可用充值套餐列表"""
    return credits_service.get_available_plans()

def reset_free_credits(user_id: str) -> bool:
    """重置用户免费额度（管理员功能）"""
    return credits_service.reset_free_credits(user_id)


# ============================================================
# 测试入口
# ============================================================
if __name__ == "__main__":
    # 简单测试
    test_user_id = "test_user_001"
    
    print(f"=== 测试用户: {test_user_id} ===")
    
    # 查询余额
    credits = get_user_credits(test_user_id)
    print(f"初始余额: {json.dumps(credits, ensure_ascii=False, indent=2)}")
    
    # 消耗一次
    success, msg = consume_diagnosis(test_user_id)
    print(f"消耗诊断: {success}, {msg}")
    
    # 查询余额
    credits = get_user_credits(test_user_id)
    print(f"消耗后余额: {json.dumps(credits, ensure_ascii=False, indent=2)}")
    
    # 充值
    success, msg, recharge_info = recharge_credits(test_user_id, "basic")
    print(f"充值: {success}, {msg}")
    
    # 查询余额
    credits = get_user_credits(test_user_id)
    print(f"充值后余额: {json.dumps(credits, ensure_ascii=False, indent=2)}")
    
    # 查询历史
    history = get_consumption_history(test_user_id)
    print(f"消耗历史: {json.dumps(history, ensure_ascii=False, indent=2)}")
    
    recharge_history = get_recharge_history(test_user_id)
    print(f"充值历史: {json.dumps(recharge_history, ensure_ascii=False, indent=2)}")
    
    # 获取套餐
    plans = get_available_plans()
    print(f"可用套餐: {json.dumps(plans, ensure_ascii=False, indent=2)}")
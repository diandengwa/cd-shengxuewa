# -*- coding: utf-8 -*-
"""
数据库连接与初始化模块
支持 SQLite 数据库，包含用户、邀请码、订单、支付记录、诊断次数配额表
以及政策知识库和划片数据表
"""

import sqlite3
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DB_FILE = PROJECT_ROOT / "data" / "shengxuewa.db"


def get_db() -> sqlite3.Connection:
    """获取 SQLite 数据库连接，设置 10s 超时以处理并发锁"""
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 启用 WAL 模式提升并发性能
    conn.execute("PRAGMA foreign_keys=ON")    # 启用外键约束
    return conn


def init_db() -> None:
    """初始化数据库表结构"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 1. users 表 (NoSQL 模式存嵌套 Pydantic)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            openid TEXT PRIMARY KEY,
            data TEXT,
            last_active TEXT
        )
        """)
        
        # 2. invite_codes 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            code TEXT PRIMARY KEY,
            plan TEXT,
            source TEXT,
            status TEXT,
            created_at TEXT,
            expires_at TEXT,
            used_by TEXT,
            used_at TEXT,
            note TEXT
        )
        """)
        
        # 3. pending_orders 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_orders (
            order_id TEXT PRIMARY KEY,
            plan TEXT,
            amount TEXT,
            openid TEXT,
            status TEXT,
            created_at TEXT,
            paid_at TEXT,
            invite_code TEXT,
            note TEXT
        )
        """)
        
        # 4. payment_records 表 — 按次诊断计费记录
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT NOT NULL,
            order_id TEXT,
            diagnosis_type TEXT NOT NULL,
            diagnosis_count INTEGER NOT NULL DEFAULT 1,
            amount REAL NOT NULL DEFAULT 0.0,
            payment_method TEXT DEFAULT 'wechat',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            paid_at TEXT,
            remark TEXT,
            FOREIGN KEY (openid) REFERENCES users(openid)
        )
        """)
        
        # 5. diagnosis_credits 表 — 用户诊断次数配额
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnosis_credits (
            openid TEXT PRIMARY KEY,
            total_credits INTEGER NOT NULL DEFAULT 3,
            used_credits INTEGER NOT NULL DEFAULT 0,
            free_credits INTEGER NOT NULL DEFAULT 3,
            purchased_credits INTEGER NOT NULL DEFAULT 0,
            last_reset_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (openid) REFERENCES users(openid)
        )
        """)
        
        # 6. policy_knowledge_base 表 — 政策知识库
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS policy_knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            tags TEXT,
            source TEXT,
            publish_date TEXT,
            effective_date TEXT,
            expire_date TEXT,
            region TEXT DEFAULT '成都',
            grade_level TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        
        # 7. school_district_data 表 — 划片数据
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS school_district_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_name TEXT NOT NULL,
            school_type TEXT NOT NULL,
            district TEXT NOT NULL,
            address TEXT,
            phone TEXT,
            website TEXT,
            description TEXT,
            enrollment_policy TEXT,
            admission_score REAL,
            reputation_score REAL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        
        # 8. family_profiles 表 — 家庭档案（含诊断次数配额字段）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT NOT NULL,
            profile_name TEXT NOT NULL DEFAULT '默认档案',
            student_name TEXT,
            student_grade TEXT,
            school_name TEXT,
            district TEXT,
            diagnosis_credits INTEGER NOT NULL DEFAULT 3,
            used_diagnosis_credits INTEGER NOT NULL DEFAULT 0,
            purchased_diagnosis_credits INTEGER NOT NULL DEFAULT 0,
            last_diagnosis_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (openid) REFERENCES users(openid)
        )
        """)
        
        # 创建索引以提升查询性能
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_family_profiles_openid 
        ON family_profiles(openid)
        """)
        
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_records_openid 
        ON payment_records(openid)
        """)
        
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_records_status 
        ON payment_records(status)
        """)
        
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_diagnosis_credits_openid 
        ON diagnosis_credits(openid)
        """)
        
        conn.commit()
        logger.info("数据库表结构初始化完成")
        
    except sqlite3.Error as e:
        logger.error(f"数据库初始化失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def get_user_credits(openid: str) -> Optional[Dict[str, Any]]:
    """获取用户诊断次数配额信息"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except sqlite3.Error as e:
        logger.error(f"获取用户配额失败: {e}")
        return None
    finally:
        conn.close()


def create_user_credits(openid: str, free_credits: int = 3) -> bool:
    """为新用户创建诊断次数配额记录"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR IGNORE INTO diagnosis_credits 
        (openid, total_credits, used_credits, free_credits, purchased_credits, 
         last_reset_date, created_at, updated_at)
        VALUES (?, ?, 0, ?, 0, ?, ?, ?)
        """, (
            openid,
            free_credits,
            free_credits,
            now[:10],  # last_reset_date 只取日期部分
            now,
            now
        ))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"创建用户配额失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def deduct_diagnosis_credit(openid: str) -> bool:
    """扣除一次诊断次数，优先使用免费次数"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        # 先获取当前配额
        cursor.execute(
            "SELECT * FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        row = cursor.fetchone()
        if not row:
            logger.warning(f"用户 {openid} 无配额记录")
            return False
        
        credits = dict(row)
        now = datetime.now().isoformat()
        
        # 优先使用免费次数
        if credits['free_credits'] > 0:
            cursor.execute("""
            UPDATE diagnosis_credits 
            SET free_credits = free_credits - 1,
                used_credits = used_credits + 1,
                updated_at = ?
            WHERE openid = ?
            """, (now, openid))
        elif credits['purchased_credits'] > 0:
            cursor.execute("""
            UPDATE diagnosis_credits 
            SET purchased_credits = purchased_credits - 1,
                used_credits = used_credits + 1,
                updated_at = ?
            WHERE openid = ?
            """, (now, openid))
        else:
            logger.warning(f"用户 {openid} 无可用的诊断次数")
            return False
        
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"扣除诊断次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def add_purchased_credits(openid: str, credits: int) -> bool:
    """增加用户购买的诊断次数"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE diagnosis_credits 
        SET purchased_credits = purchased_credits + ?,
            total_credits = total_credits + ?,
            updated_at = ?
        WHERE openid = ?
        """, (credits, credits, now, openid))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"增加购买次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def create_payment_record(
    openid: str,
    diagnosis_type: str,
    amount: float,
    diagnosis_count: int = 1,
    order_id: Optional[str] = None,
    payment_method: str = 'wechat',
    remark: Optional[str] = None
) -> Optional[int]:
    """创建支付记录，返回记录ID"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO payment_records 
        (openid, order_id, diagnosis_type, diagnosis_count, amount, 
         payment_method, status, created_at, remark)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (
            openid,
            order_id,
            diagnosis_type,
            diagnosis_count,
            amount,
            payment_method,
            now,
            remark
        ))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        logger.error(f"创建支付记录失败: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def update_payment_status(
    record_id: int,
    status: str,
    paid_at: Optional[str] = None
) -> bool:
    """更新支付记录状态"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        if paid_at:
            cursor.execute("""
            UPDATE payment_records 
            SET status = ?, paid_at = ?
            WHERE id = ?
            """, (status, paid_at, record_id))
        else:
            cursor.execute("""
            UPDATE payment_records 
            SET status = ?
            WHERE id = ?
            """, (status, record_id))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"更新支付状态失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_family_profile(openid: str, profile_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """获取家庭档案信息"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        if profile_id:
            cursor.execute(
                "SELECT * FROM family_profiles WHERE id = ? AND openid = ?",
                (profile_id, openid)
            )
        else:
            cursor.execute(
                "SELECT * FROM family_profiles WHERE openid = ? ORDER BY created_at DESC LIMIT 1",
                (openid,)
            )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except sqlite3.Error as e:
        logger.error(f"获取家庭档案失败: {e}")
        return None
    finally:
        conn.close()


def create_family_profile(
    openid: str,
    profile_name: str = '默认档案',
    student_name: Optional[str] = None,
    student_grade: Optional[str] = None,
    school_name: Optional[str] = None,
    district: Optional[str] = None
) -> Optional[int]:
    """创建家庭档案"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO family_profiles 
        (openid, profile_name, student_name, student_grade, school_name, 
         district, diagnosis_credits, used_diagnosis_credits, 
         purchased_diagnosis_credits, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 3, 0, 0, ?, ?)
        """, (
            openid,
            profile_name,
            student_name,
            student_grade,
            school_name,
            district,
            now,
            now
        ))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        logger.error(f"创建家庭档案失败: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def update_family_profile_credits(
    profile_id: int,
    diagnosis_credits: int,
    used_diagnosis_credits: int,
    purchased_diagnosis_credits: int
) -> bool:
    """更新家庭档案的诊断次数信息"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE family_profiles 
        SET diagnosis_credits = ?,
            used_diagnosis_credits = ?,
            purchased_diagnosis_credits = ?,
            updated_at = ?
        WHERE id = ?
        """, (
            diagnosis_credits,
            used_diagnosis_credits,
            purchased_diagnosis_credits,
            now,
            profile_id
        ))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"更新档案诊断次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_user_payment_history(
    openid: str,
    limit: int = 10,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """获取用户支付历史记录"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM payment_records 
        WHERE openid = ? 
        ORDER BY created_at DESC 
        LIMIT ? OFFSET ?
        """, (openid, limit, offset))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"获取支付历史失败: {e}")
        return []
    finally:
        conn.close()


def check_diagnosis_availability(openid: str) -> Tuple[bool, int]:
    """检查用户是否还有可用的诊断次数，返回(是否可用, 剩余次数)"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT free_credits, purchased_credits FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        row = cursor.fetchone()
        if not row:
            # 新用户，创建默认配额
            create_user_credits(openid)
            return True, 3
        
        remaining = row['free_credits'] + row['purchased_credits']
        return remaining > 0, remaining
    except sqlite3.Error as e:
        logger.error(f"检查诊断可用性失败: {e}")
        return False, 0
    finally:
        conn.close()


def reset_free_credits() -> int:
    """重置所有用户的免费诊断次数（每月1号执行）"""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        today = now[:10]
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE diagnosis_credits 
        SET free_credits = 3,
            last_reset_date = ?,
            updated_at = ?
        WHERE last_reset_date < ? OR last_reset_date IS NULL
        """, (today, now, today))
        conn.commit()
        reset_count = cursor.rowcount
        logger.info(f"已重置 {reset_count} 个用户的免费诊断次数")
        return reset_count
    except sqlite3.Error as e:
        logger.error(f"重置免费次数失败: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    # 初始化数据库
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("数据库初始化完成！")
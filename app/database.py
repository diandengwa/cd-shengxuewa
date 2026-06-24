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
            enrollment_scope TEXT,
            enrollment_plan TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        
        # 8. family_profiles 表 — 家庭档案（新增 diagnosis_credits 字段）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT NOT NULL,
            profile_name TEXT NOT NULL DEFAULT '默认档案',
            student_name TEXT,
            student_grade TEXT,
            student_school TEXT,
            student_gender TEXT,
            student_birthday TEXT,
            parent_name TEXT,
            parent_phone TEXT,
            parent_relation TEXT,
            home_district TEXT,
            home_address TEXT,
            household_registration TEXT,
            current_school TEXT,
            current_grade TEXT,
            academic_level TEXT,
            interests TEXT,
            special_needs TEXT,
            remarks TEXT,
            diagnosis_credits INTEGER NOT NULL DEFAULT 3,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (openid) REFERENCES users(openid)
        )
        """)
        
        # 9. diagnosis_records 表 — 诊断记录
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnosis_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT NOT NULL,
            profile_id INTEGER,
            diagnosis_type TEXT NOT NULL,
            diagnosis_data TEXT,
            result_data TEXT,
            credits_used INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (openid) REFERENCES users(openid),
            FOREIGN KEY (profile_id) REFERENCES family_profiles(id)
        )
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


def update_user_credits(openid: str, total_credits: int = None, 
                       used_credits: int = None, purchased_credits: int = None) -> bool:
    """更新用户诊断次数配额"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # 先检查用户是否存在
        cursor.execute("SELECT openid FROM diagnosis_credits WHERE openid = ?", (openid,))
        exists = cursor.fetchone()
        
        if exists:
            # 更新现有记录
            updates = []
            params = []
            if total_credits is not None:
                updates.append("total_credits = ?")
                params.append(total_credits)
            if used_credits is not None:
                updates.append("used_credits = ?")
                params.append(used_credits)
            if purchased_credits is not None:
                updates.append("purchased_credits = ?")
                params.append(purchased_credits)
            
            updates.append("updated_at = ?")
            params.append(now)
            params.append(openid)
            
            cursor.execute(
                f"UPDATE diagnosis_credits SET {', '.join(updates)} WHERE openid = ?",
                params
            )
        else:
            # 创建新记录
            cursor.execute("""
                INSERT INTO diagnosis_credits 
                (openid, total_credits, used_credits, free_credits, purchased_credits, 
                 last_reset_date, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                openid,
                total_credits or 3,
                used_credits or 0,
                3,  # 默认免费次数
                purchased_credits or 0,
                now,
                now,
                now
            ))
        
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"更新用户配额失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def deduct_credits(openid: str, count: int = 1) -> bool:
    """扣除用户诊断次数"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # 获取当前配额
        cursor.execute(
            "SELECT total_credits, used_credits FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        row = cursor.fetchone()
        
        if not row:
            logger.warning(f"用户 {openid} 没有配额记录")
            return False
        
        total = row["total_credits"]
        used = row["used_credits"]
        
        if used + count > total:
            logger.warning(f"用户 {openid} 配额不足: 已用 {used}/{total}")
            return False
        
        # 扣除次数
        cursor.execute("""
            UPDATE diagnosis_credits 
            SET used_credits = ?, updated_at = ?
            WHERE openid = ?
        """, (used + count, now, openid))
        
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"扣除用户配额失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def add_payment_record(openid: str, diagnosis_type: str, amount: float,
                      diagnosis_count: int = 1, order_id: str = None,
                      payment_method: str = 'wechat', remark: str = None) -> Optional[int]:
    """添加支付记录"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute("""
            INSERT INTO payment_records 
            (openid, order_id, diagnosis_type, diagnosis_count, amount, 
             payment_method, status, created_at, remark)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (openid, order_id, diagnosis_type, diagnosis_count, amount,
              payment_method, now, remark))
        
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        logger.error(f"添加支付记录失败: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def update_payment_status(record_id: int, status: str, paid_at: str = None) -> bool:
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


def get_user_payment_records(openid: str, limit: int = 10) -> List[Dict[str, Any]]:
    """获取用户支付记录"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM payment_records 
            WHERE openid = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (openid, limit))
        
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"获取支付记录失败: {e}")
        return []
    finally:
        conn.close()


def get_family_profile(openid: str, profile_id: int = None) -> Optional[Dict[str, Any]]:
    """获取家庭档案"""
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
                "SELECT * FROM family_profiles WHERE openid = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
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


def create_family_profile(openid: str, profile_data: Dict[str, Any]) -> Optional[int]:
    """创建家庭档案"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # 设置默认值
        profile_data.setdefault('profile_name', '默认档案')
        profile_data.setdefault('diagnosis_credits', 3)
        profile_data.setdefault('is_active', 1)
        
        fields = ['openid', 'profile_name', 'student_name', 'student_grade', 
                  'student_school', 'student_gender', 'student_birthday',
                  'parent_name', 'parent_phone', 'parent_relation',
                  'home_district', 'home_address', 'household_registration',
                  'current_school', 'current_grade', 'academic_level',
                  'interests', 'special_needs', 'remarks', 'diagnosis_credits',
                  'is_active', 'created_at', 'updated_at']
        
        values = [openid]
        for field in fields[1:]:
            if field in ['created_at', 'updated_at']:
                values.append(now)
            else:
                values.append(profile_data.get(field))
        
        placeholders = ', '.join(['?' for _ in fields])
        field_names = ', '.join(fields)
        
        cursor.execute(
            f"INSERT INTO family_profiles ({field_names}) VALUES ({placeholders})",
            values
        )
        
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        logger.error(f"创建家庭档案失败: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def update_family_profile(profile_id: int, openid: str, profile_data: Dict[str, Any]) -> bool:
    """更新家庭档案"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # 构建更新语句
        updates = []
        params = []
        
        allowed_fields = ['profile_name', 'student_name', 'student_grade', 
                         'student_school', 'student_gender', 'student_birthday',
                         'parent_name', 'parent_phone', 'parent_relation',
                         'home_district', 'home_address', 'household_registration',
                         'current_school', 'current_grade', 'academic_level',
                         'interests', 'special_needs', 'remarks', 'diagnosis_credits',
                         'is_active']
        
        for field in allowed_fields:
            if field in profile_data:
                updates.append(f"{field} = ?")
                params.append(profile_data[field])
        
        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(profile_id)
            params.append(openid)
            
            cursor.execute(
                f"UPDATE family_profiles SET {', '.join(updates)} WHERE id = ? AND openid = ?",
                params
            )
            
            conn.commit()
            return cursor.rowcount > 0
        
        return False
    except sqlite3.Error as e:
        logger.error(f"更新家庭档案失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def create_diagnosis_record(openid: str, diagnosis_type: str, 
                           profile_id: int = None, diagnosis_data: str = None,
                           credits_used: int = 1) -> Optional[int]:
    """创建诊断记录"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute("""
            INSERT INTO diagnosis_records 
            (openid, profile_id, diagnosis_type, diagnosis_data, credits_used, 
             status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """, (openid, profile_id, diagnosis_type, diagnosis_data, credits_used, now))
        
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        logger.error(f"创建诊断记录失败: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def update_diagnosis_record(record_id: int, result_data: str = None, 
                           status: str = 'completed') -> bool:
    """更新诊断记录"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        if status == 'completed':
            cursor.execute("""
                UPDATE diagnosis_records 
                SET result_data = ?, status = ?, completed_at = ?
                WHERE id = ?
            """, (result_data, status, now, record_id))
        else:
            cursor.execute("""
                UPDATE diagnosis_records 
                SET result_data = ?, status = ?
                WHERE id = ?
            """, (result_data, status, record_id))
        
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"更新诊断记录失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_user_diagnosis_records(openid: str, limit: int = 20) -> List[Dict[str, Any]]:
    """获取用户诊断记录"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM diagnosis_records 
            WHERE openid = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (openid, limit))
        
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"获取诊断记录失败: {e}")
        return []
    finally:
        conn.close()


def check_credits_available(openid: str, count: int = 1) -> bool:
    """检查用户是否有足够的诊断次数"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT total_credits, used_credits FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        row = cursor.fetchone()
        
        if not row:
            # 新用户默认有3次免费机会
            return count <= 3
        
        return (row["total_credits"] - row["used_credits"]) >= count
    except sqlite3.Error as e:
        logger.error(f"检查配额失败: {e}")
        return False
    finally:
        conn.close()


def get_credits_summary(openid: str) -> Dict[str, Any]:
    """获取用户配额摘要"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        row = cursor.fetchone()
        
        if row:
            return {
                "total_credits": row["total_credits"],
                "used_credits": row["used_credits"],
                "available_credits": row["total_credits"] - row["used_credits"],
                "free_credits": row["free_credits"],
                "purchased_credits": row["purchased_credits"],
                "last_reset_date": row["last_reset_date"]
            }
        else:
            # 新用户默认值
            return {
                "total_credits": 3,
                "used_credits": 0,
                "available_credits": 3,
                "free_credits": 3,
                "purchased_credits": 0,
                "last_reset_date": None
            }
    except sqlite3.Error as e:
        logger.error(f"获取配额摘要失败: {e}")
        return {}
    finally:
        conn.close()


if __name__ == "__main__":
    # 测试数据库初始化
    logging.basicConfig(level=logging.INFO)
    init_db()
    logger.info("数据库初始化完成")
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
            coordinates TEXT,
            enrollment_range TEXT,
            admission_policy TEXT,
            contact_info TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        
        # 8. family_profiles 表 — 家庭档案（增加 diagnosis_credits 列）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT NOT NULL,
            profile_data TEXT NOT NULL,
            diagnosis_credits INTEGER NOT NULL DEFAULT 3,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (openid) REFERENCES users(openid)
        )
        """)
        
        # 检查是否需要为 family_profiles 表添加 diagnosis_credits 列（兼容旧表）
        cursor.execute("PRAGMA table_info(family_profiles)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'diagnosis_credits' not in columns:
            try:
                cursor.execute("ALTER TABLE family_profiles ADD COLUMN diagnosis_credits INTEGER NOT NULL DEFAULT 3")
                logger.info("已为 family_profiles 表添加 diagnosis_credits 列")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    logger.warning(f"添加 diagnosis_credits 列失败: {e}")
        
        # 检查是否需要为 payment_records 表添加索引
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_records_openid 
        ON payment_records(openid)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_records_status 
        ON payment_records(status)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_records_created_at 
        ON payment_records(created_at)
        """)
        
        # 检查是否需要为 diagnosis_credits 表添加索引
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_diagnosis_credits_openid 
        ON diagnosis_credits(openid)
        """)
        
        # 检查是否需要为 family_profiles 表添加索引
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_family_profiles_openid 
        ON family_profiles(openid)
        """)
        
        conn.commit()
        logger.info("数据库表结构初始化完成")
        
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate_db() -> None:
    """执行数据库迁移：添加新表和列"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 1. 创建 payment_records 表（如果不存在）
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
        
        # 2. 创建 diagnosis_credits 表（如果不存在）
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
        
        # 3. 创建 family_profiles 表（如果不存在）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT NOT NULL,
            profile_data TEXT NOT NULL,
            diagnosis_credits INTEGER NOT NULL DEFAULT 3,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (openid) REFERENCES users(openid)
        )
        """)
        
        # 4. 为 family_profiles 表添加 diagnosis_credits 列（兼容旧表）
        cursor.execute("PRAGMA table_info(family_profiles)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'diagnosis_credits' not in columns:
            try:
                cursor.execute("ALTER TABLE family_profiles ADD COLUMN diagnosis_credits INTEGER NOT NULL DEFAULT 3")
                logger.info("已为 family_profiles 表添加 diagnosis_credits 列")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    logger.warning(f"添加 diagnosis_credits 列失败: {e}")
        
        # 5. 创建索引
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_records_openid 
        ON payment_records(openid)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_records_status 
        ON payment_records(status)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_records_created_at 
        ON payment_records(created_at)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_diagnosis_credits_openid 
        ON diagnosis_credits(openid)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_family_profiles_openid 
        ON family_profiles(openid)
        """)
        
        conn.commit()
        logger.info("数据库迁移完成")
        
    except Exception as e:
        logger.error(f"数据库迁移失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def get_user_diagnosis_credits(openid: str) -> Optional[Dict[str, Any]]:
    """获取用户诊断次数配额信息"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT * FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        row = cursor.fetchone()
        
        if row:
            return {
                "openid": row["openid"],
                "total_credits": row["total_credits"],
                "used_credits": row["used_credits"],
                "free_credits": row["free_credits"],
                "purchased_credits": row["purchased_credits"],
                "last_reset_date": row["last_reset_date"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
        return None
        
    except Exception as e:
        logger.error(f"获取用户诊断次数配额失败: {e}")
        return None
    finally:
        conn.close()


def create_user_diagnosis_credits(openid: str, free_credits: int = 3) -> bool:
    """创建用户诊断次数配额记录"""
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    try:
        cursor.execute("""
        INSERT OR REPLACE INTO diagnosis_credits 
        (openid, total_credits, used_credits, free_credits, purchased_credits, created_at, updated_at)
        VALUES (?, ?, 0, ?, 0, ?, ?)
        """, (openid, free_credits, free_credits, now, now))
        
        conn.commit()
        logger.info(f"为用户 {openid} 创建诊断次数配额成功")
        return True
        
    except Exception as e:
        logger.error(f"创建用户诊断次数配额失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def deduct_diagnosis_credit(openid: str) -> bool:
    """扣除用户一次诊断次数"""
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    try:
        # 先检查用户是否有足够的次数
        cursor.execute(
            "SELECT total_credits, used_credits FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        row = cursor.fetchone()
        
        if not row:
            logger.warning(f"用户 {openid} 没有诊断次数配额记录")
            return False
        
        remaining = row["total_credits"] - row["used_credits"]
        if remaining <= 0:
            logger.warning(f"用户 {openid} 诊断次数已用完")
            return False
        
        # 扣除一次
        cursor.execute("""
        UPDATE diagnosis_credits 
        SET used_credits = used_credits + 1, updated_at = ?
        WHERE openid = ?
        """, (now, openid))
        
        conn.commit()
        logger.info(f"为用户 {openid} 扣除一次诊断次数成功")
        return True
        
    except Exception as e:
        logger.error(f"扣除用户诊断次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def add_purchased_credits(openid: str, credits: int) -> bool:
    """增加用户购买的诊断次数"""
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    try:
        cursor.execute("""
        UPDATE diagnosis_credits 
        SET total_credits = total_credits + ?,
            purchased_credits = purchased_credits + ?,
            updated_at = ?
        WHERE openid = ?
        """, (credits, credits, now, openid))
        
        if cursor.rowcount == 0:
            # 如果用户没有记录，创建新记录
            cursor.execute("""
            INSERT INTO diagnosis_credits 
            (openid, total_credits, used_credits, free_credits, purchased_credits, created_at, updated_at)
            VALUES (?, ?, 0, 0, ?, ?, ?)
            """, (openid, credits, credits, now, now))
        
        conn.commit()
        logger.info(f"为用户 {openid} 增加 {credits} 次购买诊断次数成功")
        return True
        
    except Exception as e:
        logger.error(f"增加用户购买诊断次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def create_payment_record(openid: str, diagnosis_type: str, amount: float, 
                         diagnosis_count: int = 1, order_id: Optional[str] = None,
                         payment_method: str = 'wechat') -> Optional[int]:
    """创建支付记录"""
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    try:
        cursor.execute("""
        INSERT INTO payment_records 
        (openid, order_id, diagnosis_type, diagnosis_count, amount, payment_method, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (openid, order_id, diagnosis_type, diagnosis_count, amount, payment_method, now))
        
        conn.commit()
        record_id = cursor.lastrowid
        logger.info(f"创建支付记录成功，ID: {record_id}")
        return record_id
        
    except Exception as e:
        logger.error(f"创建支付记录失败: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def update_payment_status(record_id: int, status: str, paid_at: Optional[str] = None) -> bool:
    """更新支付记录状态"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
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
        logger.info(f"更新支付记录 {record_id} 状态为 {status} 成功")
        return True
        
    except Exception as e:
        logger.error(f"更新支付记录状态失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_payment_records(openid: Optional[str] = None, status: Optional[str] = None,
                       limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
    """获取支付记录列表"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        query = "SELECT * FROM payment_records WHERE 1=1"
        params = []
        
        if openid:
            query += " AND openid = ?"
            params.append(openid)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        records = []
        for row in rows:
            records.append({
                "id": row["id"],
                "openid": row["openid"],
                "order_id": row["order_id"],
                "diagnosis_type": row["diagnosis_type"],
                "diagnosis_count": row["diagnosis_count"],
                "amount": row["amount"],
                "payment_method": row["payment_method"],
                "status": row["status"],
                "created_at": row["created_at"],
                "paid_at": row["paid_at"],
                "remark": row["remark"]
            })
        
        return records
        
    except Exception as e:
        logger.error(f"获取支付记录失败: {e}")
        return []
    finally:
        conn.close()


def get_family_profile(openid: str) -> Optional[Dict[str, Any]]:
    """获取家庭档案"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT * FROM family_profiles WHERE openid = ? ORDER BY created_at DESC LIMIT 1",
            (openid,)
        )
        row = cursor.fetchone()
        
        if row:
            return {
                "id": row["id"],
                "openid": row["openid"],
                "profile_data": row["profile_data"],
                "diagnosis_credits": row["diagnosis_credits"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
        return None
        
    except Exception as e:
        logger.error(f"获取家庭档案失败: {e}")
        return None
    finally:
        conn.close()


def update_family_profile_diagnosis_credits(openid: str, credits: int) -> bool:
    """更新家庭档案中的诊断次数"""
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    try:
        cursor.execute("""
        UPDATE family_profiles 
        SET diagnosis_credits = ?, updated_at = ?
        WHERE openid = ?
        """, (credits, now, openid))
        
        conn.commit()
        logger.info(f"更新用户 {openid} 家庭档案诊断次数为 {credits} 成功")
        return True
        
    except Exception as e:
        logger.error(f"更新家庭档案诊断次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    # 设置日志格式
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 执行数据库迁移
    logger.info("开始执行数据库迁移...")
    migrate_db()
    logger.info("数据库迁移完成")
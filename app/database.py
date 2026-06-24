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
            enrollment_scope TEXT,
            admission_policy TEXT,
            contact_phone TEXT,
            website TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        
        # 创建索引以提升查询性能
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
        CREATE INDEX IF NOT EXISTS idx_policy_knowledge_base_category 
        ON policy_knowledge_base(category)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_policy_knowledge_base_region 
        ON policy_knowledge_base(region)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_school_district_data_district 
        ON school_district_data(district)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_school_district_data_school_type 
        ON school_district_data(school_type)
        """)
        
        conn.commit()
        logger.info("数据库表结构初始化完成")
        
    except sqlite3.Error as e:
        logger.error(f"数据库初始化失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def get_payment_record(record_id: int) -> Optional[Dict[str, Any]]:
    """根据记录ID获取支付记录"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM payment_records WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logger.error(f"获取支付记录失败: {e}")
        return None
    finally:
        conn.close()


def get_payment_records_by_openid(openid: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
    """根据用户openid获取支付记录列表"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM payment_records WHERE openid = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (openid, limit, offset)
        )
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"获取用户支付记录失败: {e}")
        return []
    finally:
        conn.close()


def create_payment_record(openid: str, diagnosis_type: str, amount: float, 
                          diagnosis_count: int = 1, order_id: Optional[str] = None,
                          payment_method: str = 'wechat', remark: Optional[str] = None) -> Optional[int]:
    """创建新的支付记录，返回记录ID"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
        INSERT INTO payment_records (openid, order_id, diagnosis_type, diagnosis_count, 
                                     amount, payment_method, status, created_at, remark)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (openid, order_id, diagnosis_type, diagnosis_count, amount, payment_method, now, remark))
        conn.commit()
        record_id = cursor.lastrowid
        logger.info(f"创建支付记录成功: ID={record_id}, openid={openid}, amount={amount}")
        return record_id
    except sqlite3.Error as e:
        logger.error(f"创建支付记录失败: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def update_payment_status(record_id: int, status: str, paid_at: Optional[str] = None) -> bool:
    """更新支付记录状态"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        if paid_at:
            cursor.execute(
                "UPDATE payment_records SET status = ?, paid_at = ? WHERE id = ?",
                (status, paid_at, record_id)
            )
        else:
            cursor.execute(
                "UPDATE payment_records SET status = ? WHERE id = ?",
                (status, record_id)
            )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"更新支付记录状态失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_diagnosis_credits(openid: str) -> Optional[Dict[str, Any]]:
    """获取用户诊断次数配额信息"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM diagnosis_credits WHERE openid = ?", (openid,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logger.error(f"获取用户诊断配额失败: {e}")
        return None
    finally:
        conn.close()


def create_diagnosis_credits(openid: str, free_credits: int = 3) -> bool:
    """为用户创建初始诊断次数配额"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
        INSERT OR IGNORE INTO diagnosis_credits (openid, total_credits, used_credits, 
                                                  free_credits, purchased_credits, 
                                                  last_reset_date, created_at, updated_at)
        VALUES (?, ?, 0, ?, 0, ?, ?, ?)
        """, (openid, free_credits, free_credits, now, now, now))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"创建用户诊断配额失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def deduct_diagnosis_credit(openid: str) -> bool:
    """扣除用户一次诊断次数，优先使用免费次数"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        # 获取当前配额
        cursor.execute("SELECT * FROM diagnosis_credits WHERE openid = ?", (openid,))
        row = cursor.fetchone()
        if not row:
            logger.warning(f"用户 {openid} 没有诊断配额记录")
            return False
        
        credits = dict(row)
        if credits['free_credits'] > 0:
            # 优先使用免费次数
            cursor.execute("""
            UPDATE diagnosis_credits 
            SET free_credits = free_credits - 1, 
                used_credits = used_credits + 1,
                updated_at = ?
            WHERE openid = ? AND free_credits > 0
            """, (datetime.now().isoformat(), openid))
        elif credits['purchased_credits'] > 0:
            # 使用购买次数
            cursor.execute("""
            UPDATE diagnosis_credits 
            SET purchased_credits = purchased_credits - 1, 
                used_credits = used_credits + 1,
                updated_at = ?
            WHERE openid = ? AND purchased_credits > 0
            """, (datetime.now().isoformat(), openid))
        else:
            logger.warning(f"用户 {openid} 没有可用诊断次数")
            return False
        
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"扣除诊断次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def add_purchased_credits(openid: str, credits: int) -> bool:
    """为用户添加购买的诊断次数"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
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
        logger.error(f"添加购买诊断次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_available_credits(openid: str) -> int:
    """获取用户可用诊断次数"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT free_credits + purchased_credits as available FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        row = cursor.fetchone()
        return row['available'] if row else 0
    except sqlite3.Error as e:
        logger.error(f"获取可用诊断次数失败: {e}")
        return 0
    finally:
        conn.close()
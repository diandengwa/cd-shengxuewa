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
            district TEXT,
            address TEXT,
            enrollment_range TEXT,
            contact_phone TEXT,
            website TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        
        # 8. family_profiles 表 — 家庭档案（用于按次诊断计费）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT NOT NULL,
            profile_name TEXT NOT NULL DEFAULT '默认档案',
            student_name TEXT,
            student_grade TEXT,
            student_school TEXT,
            diagnosis_credits INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (openid) REFERENCES users(openid)
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


def run_migrations() -> None:
    """执行数据库迁移逻辑，确保表结构与最新版本一致"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 检查 family_profiles 表是否存在 diagnosis_credits 列
        cursor.execute("PRAGMA table_info(family_profiles)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'diagnosis_credits' not in columns:
            logger.info("迁移: 为 family_profiles 表添加 diagnosis_credits 列")
            cursor.execute("""
            ALTER TABLE family_profiles 
            ADD COLUMN diagnosis_credits INTEGER NOT NULL DEFAULT 0
            """)
            conn.commit()
            logger.info("迁移完成: 添加 diagnosis_credits 列成功")
        
        # 检查 payment_records 表是否存在
        cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='payment_records'
        """)
        if not cursor.fetchone():
            logger.info("迁移: 创建 payment_records 表")
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
            conn.commit()
            logger.info("迁移完成: 创建 payment_records 表成功")
        
        # 检查 diagnosis_credits 表是否存在
        cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='diagnosis_credits'
        """)
        if not cursor.fetchone():
            logger.info("迁移: 创建 diagnosis_credits 表")
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
            conn.commit()
            logger.info("迁移完成: 创建 diagnosis_credits 表成功")
        
        logger.info("数据库迁移检查完成")
        
    except sqlite3.Error as e:
        logger.error(f"数据库迁移失败: {e}")
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


def update_user_credits(openid: str, credits_data: Dict[str, Any]) -> bool:
    """更新用户诊断次数配额"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # 检查记录是否存在
        cursor.execute(
            "SELECT openid FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        exists = cursor.fetchone()
        
        if exists:
            # 更新现有记录
            cursor.execute("""
            UPDATE diagnosis_credits 
            SET total_credits = ?,
                used_credits = ?,
                free_credits = ?,
                purchased_credits = ?,
                last_reset_date = ?,
                updated_at = ?
            WHERE openid = ?
            """, (
                credits_data.get('total_credits', 3),
                credits_data.get('used_credits', 0),
                credits_data.get('free_credits', 3),
                credits_data.get('purchased_credits', 0),
                credits_data.get('last_reset_date'),
                now,
                openid
            ))
        else:
            # 插入新记录
            cursor.execute("""
            INSERT INTO diagnosis_credits 
            (openid, total_credits, used_credits, free_credits, 
             purchased_credits, last_reset_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                openid,
                credits_data.get('total_credits', 3),
                credits_data.get('used_credits', 0),
                credits_data.get('free_credits', 3),
                credits_data.get('purchased_credits', 0),
                credits_data.get('last_reset_date'),
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


def create_payment_record(record_data: Dict[str, Any]) -> Optional[int]:
    """创建支付记录，返回记录ID"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute("""
        INSERT INTO payment_records 
        (openid, order_id, diagnosis_type, diagnosis_count, 
         amount, payment_method, status, created_at, remark)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record_data['openid'],
            record_data.get('order_id'),
            record_data['diagnosis_type'],
            record_data.get('diagnosis_count', 1),
            record_data['amount'],
            record_data.get('payment_method', 'wechat'),
            record_data.get('status', 'pending'),
            now,
            record_data.get('remark')
        ))
        
        conn.commit()
        return cursor.lastrowid
        
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


def deduct_diagnosis_credit(openid: str) -> bool:
    """扣除一次诊断次数"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # 检查是否有可用次数
        cursor.execute("""
        SELECT total_credits, used_credits 
        FROM diagnosis_credits 
        WHERE openid = ?
        """, (openid,))
        
        row = cursor.fetchone()
        if not row:
            logger.warning(f"用户 {openid} 没有配额记录")
            return False
        
        total = row['total_credits']
        used = row['used_credits']
        
        if used >= total:
            logger.warning(f"用户 {openid} 诊断次数已用完")
            return False
        
        # 扣除一次
        cursor.execute("""
        UPDATE diagnosis_credits 
        SET used_credits = used_credits + 1,
            updated_at = ?
        WHERE openid = ?
        """, (now, openid))
        
        conn.commit()
        return True
        
    except sqlite3.Error as e:
        logger.error(f"扣除诊断次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def add_purchased_credits(openid: str, credits: int) -> bool:
    """增加购买的诊断次数"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # 检查记录是否存在
        cursor.execute(
            "SELECT openid FROM diagnosis_credits WHERE openid = ?",
            (openid,)
        )
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute("""
            UPDATE diagnosis_credits 
            SET total_credits = total_credits + ?,
                purchased_credits = purchased_credits + ?,
                updated_at = ?
            WHERE openid = ?
            """, (credits, credits, now, openid))
        else:
            cursor.execute("""
            INSERT INTO diagnosis_credits 
            (openid, total_credits, used_credits, free_credits, 
             purchased_credits, created_at, updated_at)
            VALUES (?, ?, 0, 0, ?, ?, ?)
            """, (openid, credits, credits, now, now))
        
        conn.commit()
        return True
        
    except sqlite3.Error as e:
        logger.error(f"增加购买次数失败: {e}")
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


def update_family_profile_credits(openid: str, credits: int, profile_id: Optional[int] = None) -> bool:
    """更新家庭档案的诊断次数"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        if profile_id:
            cursor.execute("""
            UPDATE family_profiles 
            SET diagnosis_credits = ?, updated_at = ?
            WHERE id = ? AND openid = ?
            """, (credits, now, profile_id, openid))
        else:
            cursor.execute("""
            UPDATE family_profiles 
            SET diagnosis_credits = ?, updated_at = ?
            WHERE openid = ?
            """, (credits, now, openid))
        
        conn.commit()
        return cursor.rowcount > 0
        
    except sqlite3.Error as e:
        logger.error(f"更新家庭档案次数失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# 初始化时自动执行迁移
if __name__ != "__main__":
    try:
        run_migrations()
    except Exception as e:
        logger.warning(f"数据库迁移执行异常: {e}")
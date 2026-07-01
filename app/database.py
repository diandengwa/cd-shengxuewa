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

from sqlalchemy.orm import declarative_base
Base = declarative_base()


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
            contact_phone TEXT,
            website TEXT,
            description TEXT,
            enrollment_scope TEXT,
            admission_policy TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        
        # 8. diagnosis_prices 表 — 诊断类型价格配置
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnosis_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diagnosis_type TEXT NOT NULL UNIQUE,
            price REAL NOT NULL DEFAULT 0.0,
            description TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        
        # 插入默认诊断价格配置（如果不存在）
        cursor.execute("""
        INSERT OR IGNORE INTO diagnosis_prices (diagnosis_type, price, description, created_at, updated_at)
        VALUES 
            ('basic', 9.90, '基础诊断：学校匹配与政策解读', datetime('now'), datetime('now')),
            ('advanced', 29.90, '高级诊断：个性化升学方案', datetime('now'), datetime('now')),
            ('premium', 99.90, '尊享诊断：一对一专家咨询', datetime('now'), datetime('now'))
        """)
        
        # === 新增合规与业务表 ===
        
        # 家庭画像表（独立于 users.data JSON）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            openid TEXT PRIMARY KEY,
            stage TEXT,
            hukou_type TEXT,
            hukou_district TEXT,
            live_district TEXT,
            social_security TEXT,
            school_type TEXT,
            extra_data TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (openid) REFERENCES users(openid)
        )
        """)
        
        # 诊断报告存储表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnosis_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT NOT NULL,
            stage TEXT,
            result_json TEXT NOT NULL,
            report_title TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (openid) REFERENCES users(openid)
        )
        """)
        
        # 审计日志表（合规要求）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT,
            action TEXT NOT NULL,
            endpoint TEXT,
            ip_address TEXT,
            user_agent TEXT,
            request_body TEXT,
            response_status INTEGER,
            created_at TEXT NOT NULL
        )
        """)
        
        # 内容安全日志表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_safety_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT,
            direction TEXT NOT NULL,
            original_text TEXT,
            filtered_text TEXT,
            triggered_words TEXT,
            action_taken TEXT,
            created_at TEXT NOT NULL
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


def migrate_payment_records() -> None:
    """
    迁移 payment_records 表结构
    用于在已有数据库上添加新字段或修改表结构
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 检查 payment_records 表是否存在
        cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='payment_records'
        """)
        
        if cursor.fetchone():
            # 检查是否需要添加新字段
            cursor.execute("PRAGMA table_info(payment_records)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            
            # 需要添加的字段列表
            columns_to_add = {
                'diagnosis_count': 'INTEGER NOT NULL DEFAULT 1',
                'remark': 'TEXT'
            }
            
            for col_name, col_def in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        cursor.execute(f"ALTER TABLE payment_records ADD COLUMN {col_name} {col_def}")
                        logger.info(f"为 payment_records 表添加字段: {col_name}")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"添加字段 {col_name} 失败: {e}")
            
            conn.commit()
            logger.info("payment_records 表迁移完成")
        else:
            logger.warning("payment_records 表不存在，跳过迁移")
            
    except sqlite3.Error as e:
        logger.error(f"数据库迁移失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate_diagnosis_credits() -> None:
    """
    迁移 diagnosis_credits 表结构
    用于在已有数据库上添加新字段或修改表结构
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 检查 diagnosis_credits 表是否存在
        cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='diagnosis_credits'
        """)
        
        if cursor.fetchone():
            # 检查是否需要添加新字段
            cursor.execute("PRAGMA table_info(diagnosis_credits)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            
            # 需要添加的字段列表
            columns_to_add = {
                'purchased_credits': 'INTEGER NOT NULL DEFAULT 0',
                'last_reset_date': 'TEXT'
            }
            
            for col_name, col_def in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        cursor.execute(f"ALTER TABLE diagnosis_credits ADD COLUMN {col_name} {col_def}")
                        logger.info(f"为 diagnosis_credits 表添加字段: {col_name}")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"添加字段 {col_name} 失败: {e}")
            
            conn.commit()
            logger.info("diagnosis_credits 表迁移完成")
        else:
            logger.warning("diagnosis_credits 表不存在，跳过迁移")
            
    except sqlite3.Error as e:
        logger.error(f"数据库迁移失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def run_all_migrations() -> None:
    """执行所有数据库迁移"""
    logger.info("开始执行数据库迁移...")
    
    try:
        # 先确保表结构存在
        init_db()
        
        # 执行各表迁移
        migrate_payment_records()
        migrate_diagnosis_credits()
        
        logger.info("所有数据库迁移完成")
    except Exception as e:
        logger.error(f"数据库迁移过程出错: {e}")
        raise


def get_diagnosis_prices() -> List[Dict[str, Any]]:
    """获取诊断类型价格配置"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
        SELECT diagnosis_type, price, description 
        FROM diagnosis_prices 
        WHERE is_active = 1
        """)
        
        prices = []
        for row in cursor.fetchall():
            prices.append({
                'diagnosis_type': row['diagnosis_type'],
                'price': row['price'],
                'description': row['description']
            })
        
        return prices
    except sqlite3.Error as e:
        logger.error(f"获取诊断价格失败: {e}")
        return []
    finally:
        conn.close()


def get_user_credits(openid: str) -> Optional[Dict[str, Any]]:
    """获取用户诊断次数配额"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
        SELECT total_credits, used_credits, free_credits, purchased_credits, 
               last_reset_date, created_at, updated_at
        FROM diagnosis_credits 
        WHERE openid = ?
        """, (openid,))
        
        row = cursor.fetchone()
        if row:
            return {
                'total_credits': row['total_credits'],
                'used_credits': row['used_credits'],
                'free_credits': row['free_credits'],
                'purchased_credits': row['purchased_credits'],
                'last_reset_date': row['last_reset_date'],
                'created_at': row['created_at'],
                'updated_at': row['updated_at']
            }
        return None
    except sqlite3.Error as e:
        logger.error(f"获取用户配额失败: {e}")
        return None
    finally:
        conn.close()


def create_or_update_user_credits(openid: str, credits_data: Dict[str, Any]) -> bool:
    """创建或更新用户诊断次数配额"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        now = datetime.now().isoformat()
        
        cursor.execute("""
        INSERT INTO diagnosis_credits (openid, total_credits, used_credits, free_credits, 
                                      purchased_credits, last_reset_date, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(openid) DO UPDATE SET
            total_credits = excluded.total_credits,
            used_credits = excluded.used_credits,
            free_credits = excluded.free_credits,
            purchased_credits = excluded.purchased_credits,
            last_reset_date = excluded.last_reset_date,
            updated_at = excluded.updated_at
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
    """创建支付记录"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        now = datetime.now().isoformat()
        
        cursor.execute("""
        INSERT INTO payment_records (openid, order_id, diagnosis_type, diagnosis_count,
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


def update_payment_record(record_id: int, update_data: Dict[str, Any]) -> bool:
    """更新支付记录"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        set_clauses = []
        params = []
        
        for key, value in update_data.items():
            if key in ('status', 'paid_at', 'remark', 'order_id'):
                set_clauses.append(f"{key} = ?")
                params.append(value)
        
        if not set_clauses:
            return False
        
        set_clauses.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(record_id)
        
        cursor.execute(f"""
        UPDATE payment_records 
        SET {', '.join(set_clauses)}
        WHERE id = ?
        """, params)
        
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"更新支付记录失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_user_payment_records(openid: str, limit: int = 10) -> List[Dict[str, Any]]:
    """获取用户支付记录"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
        SELECT id, openid, order_id, diagnosis_type, diagnosis_count,
               amount, payment_method, status, created_at, paid_at, remark
        FROM payment_records 
        WHERE openid = ?
        ORDER BY created_at DESC
        LIMIT ?
        """, (openid, limit))
        
        records = []
        for row in cursor.fetchall():
            records.append({
                'id': row['id'],
                'openid': row['openid'],
                'order_id': row['order_id'],
                'diagnosis_type': row['diagnosis_type'],
                'diagnosis_count': row['diagnosis_count'],
                'amount': row['amount'],
                'payment_method': row['payment_method'],
                'status': row['status'],
                'created_at': row['created_at'],
                'paid_at': row['paid_at'],
                'remark': row['remark']
            })
        
        return records
    except sqlite3.Error as e:
        logger.error(f"获取用户支付记录失败: {e}")
        return []
    finally:
        conn.close()


if __name__ == "__main__":
    # 直接运行此文件时执行数据库初始化和迁移
    logging.basicConfig(level=logging.INFO)
    run_all_migrations()
    print("数据库初始化和迁移完成")
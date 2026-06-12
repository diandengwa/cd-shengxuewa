# -*- coding: utf-8 -*-
import sqlite3
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_FILE = PROJECT_ROOT / "data" / "shengxuewa.db"

def get_db():
    """获取 SQLite 数据库连接，设置 10s 超时以处理并发锁"""
    DB_FILE.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库表结构"""
    conn = get_db()
    cursor = conn.cursor()
    
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
    
    conn.commit()
    conn.close()

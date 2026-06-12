# -*- coding: utf-8 -*-
"""
数据迁移脚本 — 将 JSON 数据导入 SQLite 数据库
"""
import sys
import os
import json
from pathlib import Path

# 插入路径以便能够正常加载 app 中的模块
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import get_db, init_db
from app.models import UserRecord

def migrate():
    # 1. 初始化数据库
    print("[MIGRATE] 初始化数据库...")
    init_db()
    
    conn = get_db()
    cursor = conn.cursor()
    
    data_dir = PROJECT_ROOT / "data"
    
    # 2. 迁移 users
    users_file = data_dir / "users.json"
    if users_file.exists():
        print(f"[MIGRATE] 发现 users.json，正在导入...")
        try:
            with open(users_file, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
            
            count = 0
            for openid, udata in users_data.items():
                # 校验格式
                user = UserRecord(**udata)
                cursor.execute(
                    "INSERT OR REPLACE INTO users (openid, data, last_active) VALUES (?, ?, ?)",
                    (openid, user.model_dump_json(), user.last_active)
                )
                count += 1
            print(f"[MIGRATE] 成功导入 {count} 个用户记录")
        except Exception as e:
            print(f"[ERROR] 迁移 users 失败: {e}")
    else:
        print("[MIGRATE] 未找到 users.json，跳过")
        
    # 3. 迁移 invite_codes
    codes_file = data_dir / "invite_codes.json"
    if codes_file.exists():
        print(f"[MIGRATE] 发现 invite_codes.json，正在导入...")
        try:
            with open(codes_file, 'r', encoding='utf-8') as f:
                codes_data = json.load(f)
                
            count = 0
            for code, cdata in codes_data.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO invite_codes 
                    (code, plan, source, status, created_at, expires_at, used_by, used_at, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (code, cdata.get("plan"), cdata.get("source"), cdata.get("status"),
                     cdata.get("created_at"), cdata.get("expires_at"), cdata.get("used_by"),
                     cdata.get("used_at"), cdata.get("note"))
                )
                count += 1
            print(f"[MIGRATE] 成功导入 {count} 个邀请码记录")
        except Exception as e:
            print(f"[ERROR] 迁移 invite_codes 失败: {e}")
    else:
        print("[MIGRATE] 未找到 invite_codes.json，跳过")

    # 4. 迁移 pending_orders
    orders_file = data_dir / "pending_orders.json"
    if orders_file.exists():
        print(f"[MIGRATE] 发现 pending_orders.json，正在导入...")
        try:
            with open(orders_file, 'r', encoding='utf-8') as f:
                orders_data = json.load(f)
                
            count = 0
            for oid, odata in orders_data.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO pending_orders 
                    (order_id, plan, amount, openid, status, created_at, paid_at, invite_code, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (oid, odata.get("plan"), odata.get("amount"), odata.get("openid"),
                     odata.get("status"), odata.get("created_at"), odata.get("paid_at"),
                     odata.get("invite_code"), odata.get("note"))
                )
                count += 1
            print(f"[MIGRATE] 成功导入 {count} 个待付款订单记录")
        except Exception as e:
            print(f"[ERROR] 迁移 pending_orders 失败: {e}")
    else:
        print("[MIGRATE] 未找到 pending_orders.json，跳过")

    conn.commit()
    conn.close()
    print("[MIGRATE] 数据迁移完成！")

if __name__ == "__main__":
    migrate()

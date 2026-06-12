# -*- coding: utf-8 -*-
"""
邀请码系统 v2.0 — 基于 SQLite 的持久化数据层
三种发放渠道：养虾群/新微信群/扫码付款
码类型：单次码(一人一码) / 批量码 / 付费码
"""

import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from .models import PlanType
from .database import get_db, init_db

logger = logging.getLogger("k12_rocket")

# 管理员密码（从环境变量读取，未设置则拒绝启动以防止安全漏洞）
import os
ADMIN_SECRET = os.getenv("K12_ADMIN_SECRET")
if not ADMIN_SECRET:
    raise ValueError("CRITICAL: K12_ADMIN_SECRET environment variable is not set! Server refuses to start for security.")

# 确保在加载时初始化表
init_db()


def _generate_code(prefix: str = "K12") -> str:
    """生成8位邀请码，格式 K12-XXXX"""
    code = secrets.token_hex(4).upper()  # 8位hex
    return f"{prefix}-{code}"


def generate_codes(
    count: int = 1,
    plan: PlanType = PlanType.LITE,
    source: str = "manual",
    expires_days: int = 90,
    note: str = "",
) -> List[dict]:
    """
    批量生成邀请码
    source: manual(手动) | yangxia(养虾群) | wechat_group(微信群) | paid(付费)
    """
    conn = get_db()
    cursor = conn.cursor()
    created = []
    expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()

    for _ in range(count):
        code_str = _generate_code()
        while True:
            cursor.execute("SELECT 1 FROM invite_codes WHERE code = ?", (code_str,))
            if not cursor.fetchone():
                break
            code_str = _generate_code()

        entry = {
            "code": code_str,
            "plan": plan.value,
            "source": source,
            "status": "active",  # active / used / expired
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at,
            "used_by": None,
            "used_at": None,
            "note": note,
        }
        
        cursor.execute(
            """
            INSERT INTO invite_codes 
            (code, plan, source, status, created_at, expires_at, used_by, used_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (code_str, plan.value, source, entry["status"], entry["created_at"], 
             expires_at, entry["used_by"], entry["used_at"], note)
        )
        created.append(entry)

    conn.commit()
    conn.close()
    logger.info(f"[邀请码] 生成{count}个 {plan.value} 码, 来源={source}")
    return created


def redeem_code(code: str, openid: str) -> Tuple[bool, str, Optional[PlanType]]:
    """
    兑换邀请码
    返回: (success, message, plan_granted)
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM invite_codes WHERE code = ?", (code,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False, "邀请码不存在", None

    if row["status"] == "used":
        conn.close()
        return False, "邀请码已被使用", None

    if row["status"] == "expired":
        conn.close()
        return False, "邀请码已过期", None

    # 检查过期
    expires_at = datetime.fromisoformat(row["expires_at"])
    if datetime.now() > expires_at:
        cursor.execute("UPDATE invite_codes SET status = 'expired' WHERE code = ?", (code,))
        conn.commit()
        conn.close()
        return False, "邀请码已过期", None

    # 兑换
    used_at = datetime.now().isoformat()
    cursor.execute(
        "UPDATE invite_codes SET status = 'used', used_by = ?, used_at = ? WHERE code = ?",
        (openid, used_at, code)
    )
    conn.commit()
    conn.close()

    plan_granted = PlanType(row["plan"])
    logger.info(f"[邀请码] 兑换成功: {code} → {openid[:8]}... plan={plan_granted.value}")
    return True, f"兑换成功！已开通{plan_granted.value}版", plan_granted


def create_pending_order(plan: PlanType, openid: str = "") -> dict:
    """
    创建待付款订单（渠道3：扫码付款后自动生成邀请码）
    """
    conn = get_db()
    cursor = conn.cursor()
    order_id = secrets.token_hex(3).upper()  # 6位hex
    order_id_str = f"K12-{order_id}"
    
    while True:
        cursor.execute("SELECT 1 FROM pending_orders WHERE order_id = ?", (order_id_str,))
        if not cursor.fetchone():
            break
        order_id = secrets.token_hex(3).upper()
        order_id_str = f"K12-{order_id}"

    order = {
        "order_id": order_id_str,
        "plan": plan.value,
        "amount": "29.9" if plan == PlanType.LITE else "99",
        "openid": openid,
        "status": "pending",  # pending / paid / cancelled
        "created_at": datetime.now().isoformat(),
        "paid_at": None,
        "invite_code": None,
        "note": "",
    }
    
    cursor.execute(
        """
        INSERT INTO pending_orders 
        (order_id, plan, amount, openid, status, created_at, paid_at, invite_code, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (order_id_str, order["plan"], order["amount"], order["openid"], order["status"],
         order["created_at"], order["paid_at"], order["invite_code"], order["note"])
    )
    conn.commit()
    conn.close()
    logger.info(f"[订单] 创建: {order_id_str} plan={plan.value}")
    return order


def confirm_order(order_id: str, admin_note: str = "") -> Tuple[bool, str, Optional[str]]:
    """
    管理员确认付款 → 自动生成邀请码
    返回: (success, message, invite_code)
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pending_orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False, "订单不存在", None

    if row["status"] == "paid":
        conn.close()
        return False, "订单已确认", row["invite_code"]

    if row["status"] == "cancelled":
        conn.close()
        return False, "订单已取消", None

    conn.close()
    
    # 确认付款，生成邀请码
    plan = PlanType(row["plan"])
    codes = generate_codes(
        count=1,
        plan=plan,
        source="paid",
        expires_days=90,
        note=f"订单{order_id} {admin_note}".strip(),
    )

    invite_code = codes[0]["code"]

    conn = get_db()
    cursor = conn.cursor()
    paid_at = datetime.now().isoformat()
    cursor.execute(
        "UPDATE pending_orders SET status = 'paid', paid_at = ?, invite_code = ?, note = ? WHERE order_id = ?",
        (paid_at, invite_code, admin_note, order_id)
    )
    conn.commit()
    conn.close()

    logger.info(f"[订单] 确认付款: {order_id} → 邀请码={invite_code}")
    return True, f"已确认，邀请码: {invite_code}", invite_code


def list_codes(
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    """列出邀请码"""
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM invite_codes WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if source:
        query += " AND source = ?"
        params.append(source)
        
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    result = []
    for r in rows:
        result.append(dict(r))
    conn.close()
    return result


def list_orders(
    status: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    """列出订单"""
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM pending_orders WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
        
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    result = []
    for r in rows:
        result.append(dict(r))
    conn.close()
    return result


def check_order_for_openid(order_id: str, openid: str) -> Optional[dict]:
    """用户查询自己的订单是否已确认（如果有邀请码则自动兑换）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pending_orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
        
    order = dict(row)
    # 只返回自己的订单
    if order.get("openid") and order["openid"] != openid:
        return None
    return order


def verify_admin(secret: str) -> bool:
    """验证管理员密码"""
    return secret == ADMIN_SECRET

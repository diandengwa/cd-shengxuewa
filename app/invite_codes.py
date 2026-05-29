"""
邀请码系统 v1.0 — 内测期替代支付
三种发放渠道：养虾群/新微信群/扫码付款
码类型：单次码(一人一码) / 批量码 / 付费码
"""

import json
import secrets
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from .models import PlanType

logger = logging.getLogger("k12_rocket")

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CODES_FILE = DATA_DIR / "invite_codes.json"
ORDERS_FILE = DATA_DIR / "pending_orders.json"

# 管理员密码（简单实现，后续可换环境变量）
ADMIN_SECRET = os.getenv("K12_ADMIN_SECRET", "dianwa2026") if (os := __import__('os')) else "dianwa2026"


def _generate_code(prefix: str = "K12") -> str:
    """生成8位邀请码，格式 K12-XXXX"""
    code = secrets.token_hex(4).upper()  # 8位hex
    return f"{prefix}-{code}"


def _load_codes() -> dict:
    if not CODES_FILE.exists():
        return {}
    try:
        with open(CODES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_codes(codes: dict):
    DATA_DIR.mkdir(exist_ok=True)
    with open(CODES_FILE, 'w', encoding='utf-8') as f:
        json.dump(codes, f, ensure_ascii=False, indent=2)


def _load_orders() -> dict:
    if not ORDERS_FILE.exists():
        return {}
    try:
        with open(ORDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_orders(orders: dict):
    DATA_DIR.mkdir(exist_ok=True)
    with open(ORDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)


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
    codes = _load_codes()
    created = []
    expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()

    for _ in range(count):
        code_str = _generate_code()
        while code_str in codes:
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
        codes[code_str] = entry
        created.append(entry)

    _save_codes(codes)
    logger.info(f"[邀请码] 生成{count}个 {plan.value} 码, 来源={source}")
    return created


def redeem_code(code: str, openid: str) -> Tuple[bool, str, Optional[PlanType]]:
    """
    兑换邀请码
    返回: (success, message, plan_granted)
    """
    codes = _load_codes()

    if code not in codes:
        return False, "邀请码不存在", None

    entry = codes[code]

    if entry["status"] == "used":
        return False, "邀请码已被使用", None

    if entry["status"] == "expired":
        return False, "邀请码已过期", None

    # 检查过期
    expires_at = datetime.fromisoformat(entry["expires_at"])
    if datetime.now() > expires_at:
        entry["status"] = "expired"
        _save_codes(codes)
        return False, "邀请码已过期", None

    # 兑换
    entry["status"] = "used"
    entry["used_by"] = openid
    entry["used_at"] = datetime.now().isoformat()
    _save_codes(codes)

    plan_granted = PlanType(entry["plan"])
    logger.info(f"[邀请码] 兑换成功: {code} → {openid[:8]}... plan={plan_granted.value}")
    return True, f"兑换成功！已开通{plan_granted.value}版", plan_granted


def create_pending_order(plan: PlanType, openid: str = "") -> dict:
    """
    创建待付款订单（渠道3：扫码付款后自动生成邀请码）
    """
    orders = _load_orders()
    order_id = secrets.token_hex(3).upper()  # 6位hex

    order = {
        "order_id": f"K12-{order_id}",
        "plan": plan.value,
        "amount": "29.9" if plan == PlanType.LITE else "99",
        "openid": openid,
        "status": "pending",  # pending / paid / cancelled
        "created_at": datetime.now().isoformat(),
        "paid_at": None,
        "invite_code": None,
        "note": "",
    }
    orders[order["order_id"]] = order
    _save_orders(orders)
    logger.info(f"[订单] 创建: {order['order_id']} plan={plan.value}")
    return order


def confirm_order(order_id: str, admin_note: str = "") -> Tuple[bool, str, Optional[str]]:
    """
    管理员确认付款 → 自动生成邀请码
    返回: (success, message, invite_code)
    """
    orders = _load_orders()

    if order_id not in orders:
        return False, "订单不存在", None

    order = orders[order_id]

    if order["status"] == "paid":
        return False, "订单已确认", order.get("invite_code")

    if order["status"] == "cancelled":
        return False, "订单已取消", None

    # 确认付款，生成邀请码
    plan = PlanType(order["plan"])
    codes = generate_codes(
        count=1,
        plan=plan,
        source="paid",
        expires_days=90,
        note=f"订单{order_id} {admin_note}".strip(),
    )

    invite_code = codes[0]["code"]

    order["status"] = "paid"
    order["paid_at"] = datetime.now().isoformat()
    order["invite_code"] = invite_code
    order["note"] = admin_note
    _save_orders(orders)

    logger.info(f"[订单] 确认付款: {order_id} → 邀请码={invite_code}")
    return True, f"已确认，邀请码: {invite_code}", invite_code


def list_codes(
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    """列出邀请码"""
    codes = _load_codes()
    result = list(codes.values())

    if status:
        result = [c for c in result if c["status"] == status]
    if source:
        result = [c for c in result if c["source"] == source]

    # 按创建时间倒序
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result[:limit]


def list_orders(
    status: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    """列出订单"""
    orders = _load_orders()
    result = list(orders.values())

    if status:
        result = [o for o in result if o["status"] == status]

    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result[:limit]


def check_order_for_openid(order_id: str, openid: str) -> Optional[dict]:
    """用户查询自己的订单是否已确认（如果有邀请码则自动兑换）"""
    orders = _load_orders()
    if order_id not in orders:
        return None
    order = orders[order_id]
    # 只返回自己的订单
    if order.get("openid") and order["openid"] != openid:
        return None
    return order


def verify_admin(secret: str) -> bool:
    """验证管理员密码"""
    return secret == ADMIN_SECRET

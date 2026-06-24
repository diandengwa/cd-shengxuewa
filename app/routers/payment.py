#!/usr/bin/env python3
"""
K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋
支付相关API路由：创建订单、支付回调、查询余额、购买套餐选项
付费模式重构 — 按次诊断计费方案
"""

import os
import sys
import json
import logging
import secrets
import hashlib
import hmac
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from decimal import Decimal

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import APIRouter, Depends, HTTPException, Request, Form, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
import sqlite3

# ============================================================
# 日志配置
# ============================================================
logger = logging.getLogger("k12.payment")

# ============================================================
# 路由定义
# ============================================================
router = APIRouter(
    prefix="/payment",
    tags=["payment"],
    responses={404: {"description": "Not found"}},
)

# ============================================================
# 模板配置
# ============================================================
templates_dir = PROJECT_ROOT / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(templates_dir))

# ============================================================
# 数据库路径
# ============================================================
DB_PATH = PROJECT_ROOT / "data" / "k12.db"
DB_PATH.parent.mkdir(exist_ok=True)

# ============================================================
# 支付配置（从环境变量读取）
# ============================================================
PAYMENT_CONFIG = {
    "wxpay_appid": os.getenv("WXPAY_APPID", ""),
    "wxpay_mchid": os.getenv("WXPAY_MCHID", ""),
    "wxpay_key": os.getenv("WXPAY_KEY", ""),
    "wxpay_notify_url": os.getenv("WXPAY_NOTIFY_URL", "https://api.example.com/payment/notify"),
    "ali_pay_appid": os.getenv("ALI_PAY_APPID", ""),
    "ali_pay_private_key": os.getenv("ALI_PAY_PRIVATE_KEY", ""),
    "ali_pay_public_key": os.getenv("ALI_PAY_PUBLIC_KEY", ""),
    "ali_pay_notify_url": os.getenv("ALI_PAY_NOTIFY_URL", "https://api.example.com/payment/notify"),
}

# ============================================================
# 套餐配置
# ============================================================
PLANS = {
    "basic": {
        "name": "基础诊断包",
        "price": 9.90,
        "diagnoses": 1,
        "description": "单次学科诊断，适合体验",
        "valid_days": 30,
    },
    "standard": {
        "name": "标准诊断包",
        "price": 29.90,
        "diagnoses": 5,
        "description": "5次学科诊断，适合短期冲刺",
        "valid_days": 90,
    },
    "premium": {
        "name": "高级诊断包",
        "price": 49.90,
        "diagnoses": 15,
        "description": "15次学科诊断，适合长期规划",
        "valid_days": 180,
    },
    "unlimited": {
        "name": "无限诊断包",
        "price": 99.90,
        "diagnoses": -1,  # -1 表示无限次
        "description": "无限次学科诊断，适合VIP用户",
        "valid_days": 365,
    },
}

# ============================================================
# Pydantic 模型
# ============================================================
class OrderCreate(BaseModel):
    """创建订单请求模型"""
    plan_id: str = Field(..., description="套餐ID: basic/standard/premium/unlimited")
    user_id: str = Field(..., description="用户ID")
    payment_method: str = Field(default="wxpay", description="支付方式: wxpay/alipay")
    
    @field_validator("plan_id")
    @classmethod
    def validate_plan_id(cls, v):
        if v not in PLANS:
            raise ValueError(f"无效的套餐ID: {v}，可选: {list(PLANS.keys())}")
        return v
    
    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v):
        if v not in ["wxpay", "alipay"]:
            raise ValueError("支付方式仅支持 wxpay 或 alipay")
        return v

class OrderResponse(BaseModel):
    """订单响应模型"""
    order_id: str
    plan_id: str
    plan_name: str
    price: float
    diagnoses: int
    valid_days: int
    status: str
    payment_url: Optional[str] = None
    created_at: str

class BalanceResponse(BaseModel):
    """余额查询响应模型"""
    user_id: str
    total_diagnoses: int
    used_diagnoses: int
    remaining_diagnoses: int
    is_unlimited: bool
    expire_date: Optional[str] = None

class PaymentNotify(BaseModel):
    """支付回调通知模型"""
    order_id: str
    transaction_id: str
    payment_method: str
    amount: float
    status: str
    sign: Optional[str] = None

# ============================================================
# 数据库操作辅助函数
# ============================================================
def get_db_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_database():
    """初始化数据库表结构"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 创建订单表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                amount REAL NOT NULL,
                payment_method TEXT NOT NULL DEFAULT 'wxpay',
                status TEXT NOT NULL DEFAULT 'pending',
                transaction_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP,
                expire_at TIMESTAMP
            )
        """)
        
        # 创建用户诊断余额表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_diagnoses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                total_diagnoses INTEGER NOT NULL DEFAULT 0,
                used_diagnoses INTEGER NOT NULL DEFAULT 0,
                is_unlimited INTEGER NOT NULL DEFAULT 0,
                expire_date TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 创建诊断使用记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diagnosis_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                order_id TEXT,
                diagnosis_type TEXT NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
        """)
        
        conn.commit()
        logger.info("数据库表初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise
    finally:
        conn.close()

# ============================================================
# 工具函数
# ============================================================
def generate_order_id() -> str:
    """生成唯一订单号"""
    timestamp = int(time.time())
    random_str = secrets.token_hex(4)
    return f"ORD{timestamp}{random_str}"

def generate_sign(data: Dict[str, Any], key: str) -> str:
    """生成签名"""
    sorted_items = sorted(data.items())
    sign_str = "&".join([f"{k}={v}" for k, v in sorted_items])
    sign_str += f"&key={key}"
    return hashlib.md5(sign_str.encode()).hexdigest().upper()

def verify_sign(data: Dict[str, Any], sign: str, key: str) -> bool:
    """验证签名"""
    return generate_sign(data, key) == sign

def get_user_balance(user_id: str) -> Optional[Dict[str, Any]]:
    """获取用户诊断余额"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM user_diagnoses WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"获取用户余额失败: {e}")
        return None
    finally:
        conn.close()

def update_user_diagnoses(user_id: str, diagnoses_count: int, valid_days: int):
    """更新用户诊断余额"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 计算过期时间
        expire_date = datetime.now() + timedelta(days=valid_days)
        
        # 检查用户是否已有余额记录
        existing = get_user_balance(user_id)
        
        if existing:
            # 更新现有记录
            if diagnoses_count == -1:  # 无限次套餐
                cursor.execute("""
                    UPDATE user_diagnoses 
                    SET total_diagnoses = -1,
                        is_unlimited = 1,
                        expire_date = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (expire_date, user_id))
            else:
                cursor.execute("""
                    UPDATE user_diagnoses 
                    SET total_diagnoses = total_diagnoses + ?,
                        expire_date = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (diagnoses_count, expire_date, user_id))
        else:
            # 创建新记录
            is_unlimited = 1 if diagnoses_count == -1 else 0
            cursor.execute("""
                INSERT INTO user_diagnoses (user_id, total_diagnoses, used_diagnoses, is_unlimited, expire_date)
                VALUES (?, ?, 0, ?, ?)
            """, (user_id, diagnoses_count, is_unlimited, expire_date))
        
        conn.commit()
        logger.info(f"用户 {user_id} 诊断余额更新成功")
    except Exception as e:
        logger.error(f"更新用户诊断余额失败: {e}")
        raise
    finally:
        conn.close()

def deduct_diagnosis(user_id: str) -> bool:
    """扣除一次诊断次数"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取用户余额
        balance = get_user_balance(user_id)
        if not balance:
            return False
        
        # 检查是否无限次
        if balance["is_unlimited"]:
            # 检查是否过期
            if balance["expire_date"]:
                expire_date = datetime.fromisoformat(balance["expire_date"])
                if expire_date < datetime.now():
                    return False
            return True
        
        # 检查剩余次数
        remaining = balance["total_diagnoses"] - balance["used_diagnoses"]
        if remaining <= 0:
            return False
        
        # 扣除一次
        cursor.execute("""
            UPDATE user_diagnoses 
            SET used_diagnoses = used_diagnoses + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (user_id,))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"扣除诊断次数失败: {e}")
        return False
    finally:
        conn.close()

# ============================================================
# API 路由
# ============================================================
@router.on_event("startup")
async def startup_event():
    """应用启动时初始化数据库"""
    init_database()

@router.get("/plans", response_model=List[Dict[str, Any]])
async def get_plans():
    """获取所有套餐列表"""
    plans_list = []
    for plan_id, plan in PLANS.items():
        plans_list.append({
            "id": plan_id,
            "name": plan["name"],
            "price": plan["price"],
            "diagnoses": plan["diagnoses"],
            "description": plan["description"],
            "valid_days": plan["valid_days"],
        })
    return plans_list

@router.post("/create_order", response_model=OrderResponse)
async def create_order(order: OrderCreate):
    """创建订单"""
    try:
        # 验证套餐
        plan = PLANS.get(order.plan_id)
        if not plan:
            raise HTTPException(status_code=400, detail="无效的套餐ID")
        
        # 生成订单号
        order_id = generate_order_id()
        
        # 计算过期时间
        expire_at = datetime.now() + timedelta(days=plan["valid_days"])
        
        # 保存订单到数据库
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO orders (order_id, user_id, plan_id, amount, payment_method, expire_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (order_id, order.user_id, order.plan_id, plan["price"], order.payment_method, expire_at))
        conn.commit()
        
        # 生成支付链接（模拟）
        payment_url = f"https://pay.example.com/pay?order_id={order_id}&amount={plan['price']}&method={order.payment_method}"
        
        logger.info(f"订单创建成功: {order_id}, 用户: {order.user_id}, 金额: {plan['price']}")
        
        return OrderResponse(
            order_id=order_id,
            plan_id=order.plan_id,
            plan_name=plan["name"],
            price=plan["price"],
            diagnoses=plan["diagnoses"],
            valid_days=plan["valid_days"],
            status="pending",
            payment_url=payment_url,
            created_at=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建订单失败: {e}")
        raise HTTPException(status_code=500, detail="创建订单失败")
    finally:
        conn.close()

@router.post("/notify")
async def payment_notify(notify: PaymentNotify):
    """支付回调通知处理"""
    try:
        logger.info(f"收到支付回调: {notify.order_id}, 状态: {notify.status}")
        
        # 验证签名（模拟）
        if notify.sign:
            sign_data = {
                "order_id": notify.order_id,
                "transaction_id": notify.transaction_id,
                "amount": notify.amount,
                "status": notify.status
            }
            if not verify_sign(sign_data, notify.sign, PAYMENT_CONFIG["wxpay_key"]):
                logger.warning(f"签名验证失败: {notify.order_id}")
                return JSONResponse(status_code=400, content={"code": "SIGN_ERROR", "message": "签名验证失败"})
        
        # 查询订单
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE order_id = ?", (notify.order_id,))
        order = cursor.fetchone()
        
        if not order:
            logger.warning(f"订单不存在: {notify.order_id}")
            return JSONResponse(status_code=404, content={"code": "ORDER_NOT_FOUND", "message": "订单不存在"})
        
        order = dict(order)
        
        # 检查订单状态
        if order["status"] != "pending":
            logger.info(f"订单已处理: {notify.order_id}, 当前状态: {order['status']}")
            return JSONResponse(content={"code": "SUCCESS", "message": "订单已处理"})
        
        # 更新订单状态
        cursor.execute("""
            UPDATE orders 
            SET status = ?, transaction_id = ?, paid_at = CURRENT_TIMESTAMP
            WHERE order_id = ?
        """, (notify.status, notify.transaction_id, notify.order_id))
        
        # 如果支付成功，更新用户诊断余额
        if notify.status == "success":
            plan = PLANS.get(order["plan_id"])
            if plan:
                update_user_diagnoses(order["user_id"], plan["diagnoses"], plan["valid_days"])
                logger.info(f"用户 {order['user_id']} 诊断余额更新成功，增加 {plan['diagnoses']} 次")
        
        conn.commit()
        logger.info(f"订单 {notify.order_id} 处理完成")
        
        return JSONResponse(content={"code": "SUCCESS", "message": "处理成功"})
    except Exception as e:
        logger.error(f"处理支付回调失败: {e}")
        return JSONResponse(status_code=500, content={"code": "ERROR", "message": "处理失败"})
    finally:
        conn.close()

@router.get("/balance/{user_id}", response_model=BalanceResponse)
async def get_balance(user_id: str):
    """查询用户诊断余额"""
    try:
        balance = get_user_balance(user_id)
        
        if not balance:
            return BalanceResponse(
                user_id=user_id,
                total_diagnoses=0,
                used_diagnoses=0,
                remaining_diagnoses=0,
                is_unlimited=False,
                expire_date=None
            )
        
        remaining = -1 if balance["is_unlimited"] else balance["total_diagnoses"] - balance["used_diagnoses"]
        
        return BalanceResponse(
            user_id=user_id,
            total_diagnoses=balance["total_diagnoses"],
            used_diagnoses=balance["used_diagnoses"],
            remaining_diagnoses=remaining,
            is_unlimited=bool(balance["is_unlimited"]),
            expire_date=balance.get("expire_date")
        )
    except Exception as e:
        logger.error(f"查询余额失败: {e}")
        raise HTTPException(status_code=500, detail="查询余额失败")

@router.get("/orders/{user_id}", response_model=List[OrderResponse])
async def get_user_orders(user_id: str):
    """获取用户订单列表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        
        orders = []
        for row in rows:
            order = dict(row)
            plan = PLANS.get(order["plan_id"], {})
            orders.append(OrderResponse(
                order_id=order["order_id"],
                plan_id=order["plan_id"],
                plan_name=plan.get("name", "未知套餐"),
                price=order["amount"],
                diagnoses=plan.get("diagnoses", 0),
                valid_days=plan.get("valid_days", 0),
                status=order["status"],
                created_at=order["created_at"]
            ))
        
        return orders
    except Exception as e:
        logger.error(f"获取订单列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取订单列表失败")
    finally:
        conn.close()

@router.get("/diagnosis/check/{user_id}")
async def check_diagnosis_available(user_id: str):
    """检查用户是否还有诊断次数"""
    try:
        balance = get_user_balance(user_id)
        
        if not balance:
            return {"available": False, "remaining": 0, "message": "暂无诊断次数"}
        
        # 检查是否无限次
        if balance["is_unlimited"]:
            # 检查是否过期
            if balance["expire_date"]:
                expire_date = datetime.fromisoformat(balance["expire_date"])
                if expire_date < datetime.now():
                    return {"available": False, "remaining": 0, "message": "诊断套餐已过期"}
            return {"available": True, "remaining": -1, "message": "无限次诊断"}
        
        remaining = balance["total_diagnoses"] - balance["used_diagnoses"]
        if remaining <= 0:
            return {"available": False, "remaining": 0, "message": "诊断次数已用完"}
        
        return {"available": True, "remaining": remaining, "message": f"剩余 {remaining} 次诊断"}
    except Exception as e:
        logger.error(f"检查诊断可用性失败: {e}")
        raise HTTPException(status_code=500, detail="检查诊断可用性失败")

@router.post("/diagnosis/use/{user_id}")
async def use_diagnosis(user_id: str, diagnosis_type: str = Form(...), description: str = Form("")):
    """使用一次诊断"""
    try:
        # 检查是否有可用次数
        check_result = await check_diagnosis_available(user_id)
        if not check_result["available"]:
            raise HTTPException(status_code=400, detail=check_result["message"])
        
        # 扣除次数
        if not deduct_diagnosis(user_id):
            raise HTTPException(status_code=500, detail="扣除诊断次数失败")
        
        # 记录使用记录
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO diagnosis_records (user_id, diagnosis_type, description)
            VALUES (?, ?, ?)
        """, (user_id, diagnosis_type, description))
        conn.commit()
        
        logger.info(f"用户 {user_id} 使用了一次 {diagnosis_type} 诊断")
        
        return {"success": True, "message": "诊断使用成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"使用诊断失败: {e}")
        raise HTTPException(status_code=500, detail="使用诊断失败")
    finally:
        conn.close()

@router.get("/diagnosis/records/{user_id}")
async def get_diagnosis_records(user_id: str, limit: int = Query(default=10, le=100)):
    """获取用户诊断使用记录"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM diagnosis_records 
            WHERE user_id = ? 
            ORDER BY used_at DESC 
            LIMIT ?
        """, (user_id, limit))
        rows = cursor.fetchall()
        
        records = []
        for row in rows:
            record = dict(row)
            records.append({
                "id": record["id"],
                "diagnosis_type": record["diagnosis_type"],
                "used_at": record["used_at"],
                "description": record.get("description", "")
            })
        
        return records
    except Exception as e:
        logger.error(f"获取诊断记录失败: {e}")
        raise HTTPException(status_code=500, detail="获取诊断记录失败")
    finally:
        conn.close()

# ============================================================
# 页面路由
# ============================================================
@router.get("/plans_page", response_class=HTMLResponse)
async def plans_page(request: Request):
    """套餐选择页面"""
    return templates.TemplateResponse(
        "payment/plans.html",
        {"request": request, "plans": PLANS}
    )

@router.get("/balance_page/{user_id}", response_class=HTMLResponse)
async def balance_page(request: Request, user_id: str):
    """余额查询页面"""
    balance = await get_balance(user_id)
    return templates.TemplateResponse(
        "payment/balance.html",
        {"request": request, "balance": balance}
    )
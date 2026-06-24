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
    amount: float
    status: str
    created_at: str
    payment_url: Optional[str] = None

class BalanceResponse(BaseModel):
    """余额查询响应模型"""
    user_id: str
    total_diagnoses: int
    used_diagnoses: int
    remaining_diagnoses: int
    is_unlimited: bool
    expire_date: Optional[str] = None

class PlanOption(BaseModel):
    """套餐选项模型"""
    plan_id: str
    name: str
    price: float
    diagnoses: int
    description: str
    valid_days: int

# ============================================================
# 数据库操作辅助函数
# ============================================================
def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_payment_tables():
    """初始化支付相关数据表"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 订单表
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
            expire_at TIMESTAMP,
            extra_info TEXT
        )
    """)
    
    # 用户诊断配额表
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
    
    # 诊断使用记录表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnosis_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            order_id TEXT,
            diagnosis_type TEXT NOT NULL,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subject TEXT,
            grade TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("支付相关数据表初始化完成")

# ============================================================
# 工具函数
# ============================================================
def generate_order_id() -> str:
    """生成唯一订单号"""
    timestamp = int(time.time() * 1000)
    random_str = secrets.token_hex(8)
    return f"ORD{timestamp}{random_str}"

def calculate_expire_date(valid_days: int) -> str:
    """计算过期日期"""
    expire_date = datetime.now() + timedelta(days=valid_days)
    return expire_date.strftime("%Y-%m-%d %H:%M:%S")

def get_user_balance(user_id: str) -> Dict[str, Any]:
    """获取用户诊断余额"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT * FROM user_diagnoses WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "user_id": row["user_id"],
            "total_diagnoses": row["total_diagnoses"],
            "used_diagnoses": row["used_diagnoses"],
            "remaining_diagnoses": -1 if row["is_unlimited"] else (row["total_diagnoses"] - row["used_diagnoses"]),
            "is_unlimited": bool(row["is_unlimited"]),
            "expire_date": row["expire_date"],
        }
    else:
        # 新用户，初始化配额
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO user_diagnoses (user_id, total_diagnoses, used_diagnoses) VALUES (?, 0, 0)",
            (user_id,)
        )
        conn.commit()
        conn.close()
        return {
            "user_id": user_id,
            "total_diagnoses": 0,
            "used_diagnoses": 0,
            "remaining_diagnoses": 0,
            "is_unlimited": False,
            "expire_date": None,
        }

def deduct_diagnosis(user_id: str, diagnosis_type: str = "normal", subject: str = None, grade: str = None) -> bool:
    """扣除一次诊断次数"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 获取用户配额
        cursor.execute(
            "SELECT * FROM user_diagnoses WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            logger.error(f"用户 {user_id} 不存在配额记录")
            return False
        
        # 检查是否无限次
        if row["is_unlimited"]:
            # 记录使用
            cursor.execute(
                "INSERT INTO diagnosis_usage (user_id, diagnosis_type, subject, grade) VALUES (?, ?, ?, ?)",
                (user_id, diagnosis_type, subject, grade)
            )
            conn.commit()
            return True
        
        # 检查剩余次数
        remaining = row["total_diagnoses"] - row["used_diagnoses"]
        if remaining <= 0:
            logger.warning(f"用户 {user_id} 诊断次数不足")
            return False
        
        # 检查是否过期
        if row["expire_date"]:
            expire_date = datetime.strptime(row["expire_date"], "%Y-%m-%d %H:%M:%S")
            if expire_date < datetime.now():
                logger.warning(f"用户 {user_id} 诊断配额已过期")
                return False
        
        # 扣除次数
        cursor.execute(
            "UPDATE user_diagnoses SET used_diagnoses = used_diagnoses + 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,)
        )
        
        # 记录使用
        cursor.execute(
            "INSERT INTO diagnosis_usage (user_id, diagnosis_type, subject, grade) VALUES (?, ?, ?, ?)",
            (user_id, diagnosis_type, subject, grade)
        )
        
        conn.commit()
        return True
        
    except Exception as e:
        conn.rollback()
        logger.error(f"扣除诊断次数失败: {str(e)}")
        return False
    finally:
        conn.close()

def add_diagnosis_quota(user_id: str, plan_id: str, order_id: str) -> bool:
    """添加诊断配额（支付成功后调用）"""
    plan = PLANS.get(plan_id)
    if not plan:
        logger.error(f"无效的套餐ID: {plan_id}")
        return False
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 获取当前配额
        cursor.execute(
            "SELECT * FROM user_diagnoses WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        
        if row:
            # 更新现有配额
            new_total = row["total_diagnoses"] + plan["diagnoses"] if plan["diagnoses"] > 0 else -1
            is_unlimited = 1 if plan["diagnoses"] == -1 else row["is_unlimited"]
            expire_date = calculate_expire_date(plan["valid_days"])
            
            cursor.execute("""
                UPDATE user_diagnoses 
                SET total_diagnoses = ?,
                    is_unlimited = ?,
                    expire_date = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (new_total, is_unlimited, expire_date, user_id))
        else:
            # 创建新配额
            total = plan["diagnoses"] if plan["diagnoses"] > 0 else -1
            is_unlimited = 1 if plan["diagnoses"] == -1 else 0
            expire_date = calculate_expire_date(plan["valid_days"])
            
            cursor.execute("""
                INSERT INTO user_diagnoses (user_id, total_diagnoses, used_diagnoses, is_unlimited, expire_date)
                VALUES (?, ?, 0, ?, ?)
            """, (user_id, total, is_unlimited, expire_date))
        
        conn.commit()
        logger.info(f"用户 {user_id} 添加诊断配额成功: plan={plan_id}, order={order_id}")
        return True
        
    except Exception as e:
        conn.rollback()
        logger.error(f"添加诊断配额失败: {str(e)}")
        return False
    finally:
        conn.close()

# ============================================================
# 支付模拟函数（实际项目中替换为真实支付SDK）
# ============================================================
def create_wxpay_order(order_id: str, amount: float, description: str) -> Dict[str, Any]:
    """模拟微信支付下单"""
    # 实际项目中替换为微信支付API调用
    logger.info(f"模拟微信支付下单: order_id={order_id}, amount={amount}")
    return {
        "success": True,
        "payment_url": f"https://wxpay.example.com/pay?order_id={order_id}",
        "prepay_id": f"prepay_{order_id}",
    }

def create_alipay_order(order_id: str, amount: float, description: str) -> Dict[str, Any]:
    """模拟支付宝下单"""
    # 实际项目中替换为支付宝API调用
    logger.info(f"模拟支付宝下单: order_id={order_id}, amount={amount}")
    return {
        "success": True,
        "payment_url": f"https://alipay.example.com/pay?order_id={order_id}",
        "trade_no": f"trade_{order_id}",
    }

def verify_wxpay_notification(data: Dict[str, Any]) -> bool:
    """验证微信支付回调签名"""
    # 实际项目中实现签名验证
    return True

def verify_alipay_notification(data: Dict[str, Any]) -> bool:
    """验证支付宝回调签名"""
    # 实际项目中实现签名验证
    return True

# ============================================================
# API 路由
# ============================================================

@router.get("/plans", response_model=List[PlanOption])
async def get_plans():
    """获取所有套餐选项"""
    plans = []
    for plan_id, plan in PLANS.items():
        plans.append(PlanOption(
            plan_id=plan_id,
            name=plan["name"],
            price=plan["price"],
            diagnoses=plan["diagnoses"],
            description=plan["description"],
            valid_days=plan["valid_days"],
        ))
    return plans

@router.post("/create_order", response_model=OrderResponse)
async def create_order(order_data: OrderCreate):
    """创建支付订单"""
    try:
        plan = PLANS[order_data.plan_id]
        order_id = generate_order_id()
        
        # 创建订单记录
        conn = get_db()
        cursor = conn.cursor()
        expire_date = calculate_expire_date(plan["valid_days"])
        
        cursor.execute("""
            INSERT INTO orders (order_id, user_id, plan_id, amount, payment_method, expire_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            order_data.user_id,
            order_data.plan_id,
            plan["price"],
            order_data.payment_method,
            expire_date,
        ))
        conn.commit()
        conn.close()
        
        # 调用支付接口
        payment_result = None
        if order_data.payment_method == "wxpay":
            payment_result = create_wxpay_order(
                order_id=order_id,
                amount=plan["price"],
                description=plan["name"],
            )
        elif order_data.payment_method == "alipay":
            payment_result = create_alipay_order(
                order_id=order_id,
                amount=plan["price"],
                description=plan["name"],
            )
        
        if payment_result and payment_result.get("success"):
            return OrderResponse(
                order_id=order_id,
                plan_id=order_data.plan_id,
                plan_name=plan["name"],
                amount=plan["price"],
                status="pending",
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                payment_url=payment_result.get("payment_url"),
            )
        else:
            raise HTTPException(status_code=500, detail="支付接口调用失败")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建订单失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建订单失败: {str(e)}")

@router.post("/notify")
async def payment_notify(request: Request):
    """支付回调通知处理"""
    try:
        # 获取回调数据
        body = await request.body()
        data = json.loads(body)
        
        logger.info(f"收到支付回调: {data}")
        
        # 验证签名（根据支付方式）
        payment_method = data.get("payment_method", "wxpay")
        if payment_method == "wxpay":
            if not verify_wxpay_notification(data):
                return JSONResponse(content={"code": "FAIL", "message": "签名验证失败"}, status_code=400)
        elif payment_method == "alipay":
            if not verify_alipay_notification(data):
                return JSONResponse(content={"code": "FAIL", "message": "签名验证失败"}, status_code=400)
        
        # 获取订单信息
        order_id = data.get("out_trade_no") or data.get("order_id")
        transaction_id = data.get("transaction_id") or data.get("trade_no")
        
        if not order_id:
            return JSONResponse(content={"code": "FAIL", "message": "缺少订单号"}, status_code=400)
        
        # 更新订单状态
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM orders WHERE order_id = ?",
            (order_id,)
        )
        order = cursor.fetchone()
        
        if not order:
            conn.close()
            return JSONResponse(content={"code": "FAIL", "message": "订单不存在"}, status_code=404)
        
        if order["status"] == "paid":
            conn.close()
            return JSONResponse(content={"code": "SUCCESS", "message": "订单已支付"})
        
        # 更新订单为已支付
        cursor.execute("""
            UPDATE orders 
            SET status = 'paid', 
                transaction_id = ?,
                paid_at = CURRENT_TIMESTAMP
            WHERE order_id = ?
        """, (transaction_id, order_id))
        
        # 添加诊断配额
        add_diagnosis_quota(
            user_id=order["user_id"],
            plan_id=order["plan_id"],
            order_id=order_id,
        )
        
        conn.commit()
        conn.close()
        
        logger.info(f"订单 {order_id} 支付成功，已为用户 {order['user_id']} 添加配额")
        
        return JSONResponse(content={"code": "SUCCESS", "message": "支付成功"})
        
    except json.JSONDecodeError:
        return JSONResponse(content={"code": "FAIL", "message": "无效的JSON数据"}, status_code=400)
    except Exception as e:
        logger.error(f"支付回调处理失败: {str(e)}")
        return JSONResponse(content={"code": "FAIL", "message": f"处理失败: {str(e)}"}, status_code=500)

@router.get("/balance/{user_id}", response_model=BalanceResponse)
async def get_balance(user_id: str):
    """查询用户诊断余额"""
    try:
        balance = get_user_balance(user_id)
        return BalanceResponse(
            user_id=balance["user_id"],
            total_diagnoses=balance["total_diagnoses"],
            used_diagnoses=balance["used_diagnoses"],
            remaining_diagnoses=balance["remaining_diagnoses"],
            is_unlimited=balance["is_unlimited"],
            expire_date=balance["expire_date"],
        )
    except Exception as e:
        logger.error(f"查询余额失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询余额失败: {str(e)}")

@router.get("/orders/{user_id}")
async def get_user_orders(user_id: str, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50)):
    """获取用户订单列表"""
    try:
        offset = (page - 1) * page_size
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 查询总数
        cursor.execute(
            "SELECT COUNT(*) as total FROM orders WHERE user_id = ?",
            (user_id,)
        )
        total = cursor.fetchone()["total"]
        
        # 查询订单列表
        cursor.execute("""
            SELECT * FROM orders 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        """, (user_id, page_size, offset))
        
        orders = []
        for row in cursor.fetchall():
            orders.append({
                "order_id": row["order_id"],
                "plan_id": row["plan_id"],
                "amount": row["amount"],
                "payment_method": row["payment_method"],
                "status": row["status"],
                "transaction_id": row["transaction_id"],
                "created_at": row["created_at"],
                "paid_at": row["paid_at"],
                "expire_at": row["expire_at"],
            })
        
        conn.close()
        
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "orders": orders,
        }
        
    except Exception as e:
        logger.error(f"查询订单列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询订单列表失败: {str(e)}")

@router.get("/usage/{user_id}")
async def get_diagnosis_usage(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50)
):
    """获取诊断使用记录"""
    try:
        offset = (page - 1) * page_size
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 查询总数
        cursor.execute(
            "SELECT COUNT(*) as total FROM diagnosis_usage WHERE user_id = ?",
            (user_id,)
        )
        total = cursor.fetchone()["total"]
        
        # 查询使用记录
        cursor.execute("""
            SELECT * FROM diagnosis_usage 
            WHERE user_id = ? 
            ORDER BY used_at DESC 
            LIMIT ? OFFSET ?
        """, (user_id, page_size, offset))
        
        records = []
        for row in cursor.fetchall():
            records.append({
                "id": row["id"],
                "order_id": row["order_id"],
                "diagnosis_type": row["diagnosis_type"],
                "used_at": row["used_at"],
                "subject": row["subject"],
                "grade": row["grade"],
            })
        
        conn.close()
        
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "records": records,
        }
        
    except Exception as e:
        logger.error(f"查询使用记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询使用记录失败: {str(e)}")

@router.post("/deduct")
async def deduct_diagnosis_api(
    user_id: str = Form(...),
    diagnosis_type: str = Form(default="normal"),
    subject: str = Form(default=None),
    grade: str = Form(default=None)
):
    """扣除诊断次数API（供其他模块调用）"""
    try:
        success = deduct_diagnosis(
            user_id=user_id,
            diagnosis_type=diagnosis_type,
            subject=subject,
            grade=grade,
        )
        
        if success:
            balance = get_user_balance(user_id)
            return {
                "success": True,
                "message": "诊断次数扣除成功",
                "remaining_diagnoses": balance["remaining_diagnoses"],
            }
        else:
            return JSONResponse(
                content={
                    "success": False,
                    "message": "诊断次数不足或已过期",
                },
                status_code=400,
            )
            
    except Exception as e:
        logger.error(f"扣除诊断次数失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"扣除诊断次数失败: {str(e)}")

@router.get("/check/{user_id}")
async def check_diagnosis_available(user_id: str):
    """检查用户是否可以进行诊断"""
    try:
        balance = get_user_balance(user_id)
        
        if balance["is_unlimited"]:
            return {
                "available": True,
                "message": "无限次诊断可用",
                "remaining": -1,
            }
        
        if balance["remaining_diagnoses"] > 0:
            # 检查是否过期
            if balance["expire_date"]:
                expire_date = datetime.strptime(balance["expire_date"], "%Y-%m-%d %H:%M:%S")
                if expire_date < datetime.now():
                    return {
                        "available": False,
                        "message": "诊断配额已过期",
                        "remaining": 0,
                    }
            
            return {
                "available": True,
                "message": f"剩余 {balance['remaining_diagnoses']} 次诊断",
                "remaining": balance["remaining_diagnoses"],
            }
        else:
            return {
                "available": False,
                "message": "诊断次数不足，请购买套餐",
                "remaining": 0,
            }
            
    except Exception as e:
        logger.error(f"检查诊断可用性失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"检查诊断可用性失败: {str(e)}")

# ============================================================
# 页面路由（Jinja2模板）
# ============================================================

@router.get("/plans_page", response_class=HTMLResponse)
async def plans_page(request: Request):
    """套餐选择页面"""
    plans = []
    for plan_id, plan in PLANS.items():
        plans.append({
            "plan_id": plan_id,
            "name": plan["name"],
            "price": plan["price"],
            "diagnoses": plan["diagnoses"],
            "description": plan["description"],
            "valid_days": plan["valid_days"],
        })
    
    return templates.TemplateResponse(
        "payment/plans.html",
        {"request": request, "plans": plans}
    )

@router.get("/balance_page/{user_id}", response_class=HTMLResponse)
async def balance_page(request: Request, user_id: str):
    """余额查询页面"""
    try:
        balance = get_user_balance(user_id)
        return templates.TemplateResponse(
            "payment/balance.html",
            {"request": request, "balance": balance}
        )
    except Exception as e:
        logger.error(f"加载余额页面失败: {str(e)}")
        raise HTTPException(status_code=500, detail="加载余额页面失败")

# ============================================================
# 初始化
# ============================================================
init_payment_tables()
logger.info("支付模块路由加载完成")
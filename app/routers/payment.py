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
    payment_url: Optional[str] = None
    created_at: str

class BalanceResponse(BaseModel):
    """余额响应模型"""
    user_id: str
    total_diagnoses: int
    used_diagnoses: int
    remaining_diagnoses: int
    is_unlimited: bool
    expires_at: Optional[str] = None

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
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except sqlite3.Error as e:
        logger.error(f"数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail="数据库连接失败")

def init_payment_tables():
    """初始化支付相关数据表"""
    try:
        conn = get_db_connection()
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
                expired_at TIMESTAMP,
                notify_data TEXT
            )
        """)
        
        # 用户诊断余额表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_diagnoses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                total_diagnoses INTEGER NOT NULL DEFAULT 0,
                used_diagnoses INTEGER NOT NULL DEFAULT 0,
                is_unlimited INTEGER NOT NULL DEFAULT 0,
                expires_at TIMESTAMP,
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
        
        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders(order_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_diagnoses_user_id ON user_diagnoses(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_diagnosis_usage_user_id ON diagnosis_usage(user_id)")
        
        conn.commit()
        logger.info("支付相关数据表初始化完成")
    except sqlite3.Error as e:
        logger.error(f"初始化支付数据表失败: {e}")
        raise
    finally:
        if conn:
            conn.close()

def generate_order_id() -> str:
    """生成唯一订单号"""
    timestamp = int(time.time() * 1000)
    random_str = secrets.token_hex(8)
    return f"ORD{timestamp}{random_str}"

def calculate_expiry(valid_days: int) -> str:
    """计算过期时间"""
    expiry = datetime.now() + timedelta(days=valid_days)
    return expiry.strftime("%Y-%m-%d %H:%M:%S")

# ============================================================
# API 路由
# ============================================================

@router.get("/plans", response_model=Dict[str, Any])
async def get_plans():
    """获取所有套餐选项"""
    try:
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
        return {
            "success": True,
            "data": plans_list,
            "total": len(plans_list)
        }
    except Exception as e:
        logger.error(f"获取套餐列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取套餐列表失败")

@router.post("/create-order", response_model=Dict[str, Any])
async def create_order(order_data: OrderCreate):
    """创建支付订单"""
    try:
        # 验证套餐
        plan = PLANS.get(order_data.plan_id)
        if not plan:
            raise HTTPException(status_code=400, detail="无效的套餐ID")
        
        # 生成订单
        order_id = generate_order_id()
        amount = plan["price"]
        expired_at = calculate_expiry(plan["valid_days"])
        
        # 保存订单到数据库
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO orders (order_id, user_id, plan_id, amount, payment_method, status, expired_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """, (order_id, order_data.user_id, order_data.plan_id, amount, order_data.payment_method, expired_at))
            conn.commit()
        except sqlite3.IntegrityError as e:
            logger.error(f"订单创建失败（重复订单号）: {e}")
            raise HTTPException(status_code=500, detail="订单创建失败，请重试")
        finally:
            conn.close()
        
        # 生成支付链接（模拟）
        payment_url = f"https://pay.example.com/pay?order_id={order_id}&amount={amount}&method={order_data.payment_method}"
        
        return {
            "success": True,
            "data": {
                "order_id": order_id,
                "plan_id": order_data.plan_id,
                "plan_name": plan["name"],
                "amount": amount,
                "status": "pending",
                "payment_url": payment_url,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "expired_at": expired_at,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建订单失败: {e}")
        raise HTTPException(status_code=500, detail="创建订单失败")

@router.post("/notify")
async def payment_notify(notify_data: PaymentNotify):
    """支付回调处理"""
    try:
        logger.info(f"收到支付回调: {notify_data.model_dump()}")
        
        # 验证签名（模拟）
        if notify_data.sign:
            expected_sign = hashlib.md5(
                f"{notify_data.order_id}{notify_data.amount}{PAYMENT_CONFIG['wxpay_key']}".encode()
            ).hexdigest()
            if notify_data.sign != expected_sign:
                logger.warning(f"支付回调签名验证失败: {notify_data.order_id}")
                return {"code": "FAIL", "message": "签名验证失败"}
        
        # 更新订单状态
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 查询订单
            cursor.execute("SELECT * FROM orders WHERE order_id = ?", (notify_data.order_id,))
            order = cursor.fetchone()
            
            if not order:
                logger.warning(f"订单不存在: {notify_data.order_id}")
                return {"code": "FAIL", "message": "订单不存在"}
            
            if order["status"] == "paid":
                logger.info(f"订单已支付，忽略重复回调: {notify_data.order_id}")
                return {"code": "SUCCESS", "message": "订单已处理"}
            
            # 更新订单状态
            cursor.execute("""
                UPDATE orders 
                SET status = 'paid', 
                    transaction_id = ?,
                    paid_at = CURRENT_TIMESTAMP,
                    notify_data = ?
                WHERE order_id = ? AND status = 'pending'
            """, (notify_data.transaction_id, json.dumps(notify_data.model_dump()), notify_data.order_id))
            
            if cursor.rowcount == 0:
                logger.warning(f"订单状态更新失败: {notify_data.order_id}")
                return {"code": "FAIL", "message": "订单状态更新失败"}
            
            # 更新用户诊断余额
            plan = PLANS.get(order["plan_id"])
            if plan:
                # 检查用户余额记录是否存在
                cursor.execute("SELECT * FROM user_diagnoses WHERE user_id = ?", (order["user_id"],))
                user_balance = cursor.fetchone()
                
                if user_balance:
                    # 更新现有余额
                    if plan["diagnoses"] == -1:  # 无限套餐
                        cursor.execute("""
                            UPDATE user_diagnoses 
                            SET total_diagnoses = total_diagnoses + ?,
                                is_unlimited = 1,
                                expires_at = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE user_id = ?
                        """, (999999, order["expired_at"], order["user_id"]))
                    else:
                        cursor.execute("""
                            UPDATE user_diagnoses 
                            SET total_diagnoses = total_diagnoses + ?,
                                expires_at = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE user_id = ?
                        """, (plan["diagnoses"], order["expired_at"], order["user_id"]))
                else:
                    # 创建新余额记录
                    if plan["diagnoses"] == -1:  # 无限套餐
                        cursor.execute("""
                            INSERT INTO user_diagnoses (user_id, total_diagnoses, used_diagnoses, is_unlimited, expires_at)
                            VALUES (?, ?, 0, 1, ?)
                        """, (order["user_id"], 999999, order["expired_at"]))
                    else:
                        cursor.execute("""
                            INSERT INTO user_diagnoses (user_id, total_diagnoses, used_diagnoses, is_unlimited, expires_at)
                            VALUES (?, ?, 0, 0, ?)
                        """, (order["user_id"], plan["diagnoses"], order["expired_at"]))
            
            conn.commit()
            logger.info(f"支付回调处理成功: {notify_data.order_id}")
            
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"支付回调数据库操作失败: {e}")
            return {"code": "FAIL", "message": "数据库操作失败"}
        finally:
            conn.close()
        
        return {"code": "SUCCESS", "message": "支付回调处理成功"}
        
    except Exception as e:
        logger.error(f"支付回调处理异常: {e}")
        return {"code": "FAIL", "message": "系统异常"}

@router.get("/balance/{user_id}", response_model=Dict[str, Any])
async def get_balance(user_id: str):
    """查询用户诊断余额"""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 查询用户余额
            cursor.execute("SELECT * FROM user_diagnoses WHERE user_id = ?", (user_id,))
            balance = cursor.fetchone()
            
            if not balance:
                return {
                    "success": True,
                    "data": {
                        "user_id": user_id,
                        "total_diagnoses": 0,
                        "used_diagnoses": 0,
                        "remaining_diagnoses": 0,
                        "is_unlimited": False,
                        "expires_at": None,
                    }
                }
            
            # 计算剩余次数
            if balance["is_unlimited"]:
                remaining = -1  # 无限次
            else:
                remaining = balance["total_diagnoses"] - balance["used_diagnoses"]
                if remaining < 0:
                    remaining = 0
            
            # 检查是否过期
            expires_at = balance["expires_at"]
            is_expired = False
            if expires_at:
                try:
                    expiry_date = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                    if expiry_date < datetime.now():
                        is_expired = True
                        remaining = 0
                except ValueError:
                    pass
            
            return {
                "success": True,
                "data": {
                    "user_id": balance["user_id"],
                    "total_diagnoses": balance["total_diagnoses"],
                    "used_diagnoses": balance["used_diagnoses"],
                    "remaining_diagnoses": remaining,
                    "is_unlimited": bool(balance["is_unlimited"]),
                    "expires_at": expires_at,
                    "is_expired": is_expired,
                }
            }
            
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"查询余额失败: {e}")
        raise HTTPException(status_code=500, detail="查询余额失败")

@router.get("/orders/{user_id}", response_model=Dict[str, Any])
async def get_user_orders(
    user_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=50, description="每页数量"),
    status: Optional[str] = Query(None, description="订单状态过滤")
):
    """查询用户订单列表"""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 构建查询条件
            where_clause = "WHERE user_id = ?"
            params = [user_id]
            
            if status:
                where_clause += " AND status = ?"
                params.append(status)
            
            # 查询总数
            cursor.execute(f"SELECT COUNT(*) FROM orders {where_clause}", params)
            total = cursor.fetchone()[0]
            
            # 查询分页数据
            offset = (page - 1) * page_size
            cursor.execute(
                f"SELECT * FROM orders {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset]
            )
            orders = cursor.fetchall()
            
            orders_list = []
            for order in orders:
                plan = PLANS.get(order["plan_id"], {})
                orders_list.append({
                    "order_id": order["order_id"],
                    "plan_id": order["plan_id"],
                    "plan_name": plan.get("name", "未知套餐"),
                    "amount": order["amount"],
                    "payment_method": order["payment_method"],
                    "status": order["status"],
                    "transaction_id": order["transaction_id"],
                    "created_at": order["created_at"],
                    "paid_at": order["paid_at"],
                    "expired_at": order["expired_at"],
                })
            
            return {
                "success": True,
                "data": {
                    "orders": orders_list,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": (total + page_size - 1) // page_size,
                }
            }
            
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"查询订单列表失败: {e}")
        raise HTTPException(status_code=500, detail="查询订单列表失败")

@router.get("/order/{order_id}", response_model=Dict[str, Any])
async def get_order_detail(order_id: str):
    """查询订单详情"""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            order = cursor.fetchone()
            
            if not order:
                raise HTTPException(status_code=404, detail="订单不存在")
            
            plan = PLANS.get(order["plan_id"], {})
            
            return {
                "success": True,
                "data": {
                    "order_id": order["order_id"],
                    "user_id": order["user_id"],
                    "plan_id": order["plan_id"],
                    "plan_name": plan.get("name", "未知套餐"),
                    "amount": order["amount"],
                    "payment_method": order["payment_method"],
                    "status": order["status"],
                    "transaction_id": order["transaction_id"],
                    "created_at": order["created_at"],
                    "paid_at": order["paid_at"],
                    "expired_at": order["expired_at"],
                }
            }
            
        finally:
            conn.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询订单详情失败: {e}")
        raise HTTPException(status_code=500, detail="查询订单详情失败")

@router.post("/use-diagnosis")
async def use_diagnosis(
    user_id: str = Form(...),
    diagnosis_type: str = Form(...),
    subject: Optional[str] = Form(None),
    grade: Optional[str] = Form(None)
):
    """使用一次诊断机会"""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 查询用户余额
            cursor.execute("SELECT * FROM user_diagnoses WHERE user_id = ?", (user_id,))
            balance = cursor.fetchone()
            
            if not balance:
                raise HTTPException(status_code=400, detail="用户没有诊断余额")
            
            # 检查是否过期
            if balance["expires_at"]:
                try:
                    expiry_date = datetime.strptime(balance["expires_at"], "%Y-%m-%d %H:%M:%S")
                    if expiry_date < datetime.now():
                        raise HTTPException(status_code=400, detail="诊断余额已过期")
                except ValueError:
                    pass
            
            # 检查剩余次数
            if not balance["is_unlimited"]:
                remaining = balance["total_diagnoses"] - balance["used_diagnoses"]
                if remaining <= 0:
                    raise HTTPException(status_code=400, detail="诊断次数已用完")
            
            # 更新使用次数
            cursor.execute("""
                UPDATE user_diagnoses 
                SET used_diagnoses = used_diagnoses + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (user_id,))
            
            # 记录使用日志
            cursor.execute("""
                INSERT INTO diagnosis_usage (user_id, diagnosis_type, subject, grade)
                VALUES (?, ?, ?, ?)
            """, (user_id, diagnosis_type, subject, grade))
            
            conn.commit()
            
            # 返回更新后的余额
            cursor.execute("SELECT * FROM user_diagnoses WHERE user_id = ?", (user_id,))
            updated_balance = cursor.fetchone()
            
            remaining = -1 if updated_balance["is_unlimited"] else \
                       updated_balance["total_diagnoses"] - updated_balance["used_diagnoses"]
            
            return {
                "success": True,
                "data": {
                    "user_id": user_id,
                    "remaining_diagnoses": remaining,
                    "is_unlimited": bool(updated_balance["is_unlimited"]),
                    "used_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            }
            
        finally:
            conn.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"使用诊断失败: {e}")
        raise HTTPException(status_code=500, detail="使用诊断失败")

@router.get("/usage-history/{user_id}", response_model=Dict[str, Any])
async def get_usage_history(
    user_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=50, description="每页数量")
):
    """查询诊断使用历史"""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 查询总数
            cursor.execute("SELECT COUNT(*) FROM diagnosis_usage WHERE user_id = ?", (user_id,))
            total = cursor.fetchone()[0]
            
            # 查询分页数据
            offset = (page - 1) * page_size
            cursor.execute(
                """SELECT * FROM diagnosis_usage 
                   WHERE user_id = ? 
                   ORDER BY used_at DESC 
                   LIMIT ? OFFSET ?""",
                (user_id, page_size, offset)
            )
            records = cursor.fetchall()
            
            usage_list = []
            for record in records:
                usage_list.append({
                    "id": record["id"],
                    "diagnosis_type": record["diagnosis_type"],
                    "subject": record["subject"],
                    "grade": record["grade"],
                    "used_at": record["used_at"],
                })
            
            return {
                "success": True,
                "data": {
                    "usage_records": usage_list,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": (total + page_size - 1) // page_size,
                }
            }
            
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"查询使用历史失败: {e}")
        raise HTTPException(status_code=500, detail="查询使用历史失败")

# ============================================================
# 页面路由
# ============================================================

@router.get("/plans-page", response_class=HTMLResponse)
async def plans_page(request: Request):
    """套餐选择页面"""
    try:
        return templates.TemplateResponse(
            "payment/plans.html",
            {
                "request": request,
                "plans": PLANS,
                "title": "选择诊断套餐",
            }
        )
    except Exception as e:
        logger.error(f"加载套餐页面失败: {e}")
        raise HTTPException(status_code=500, detail="加载页面失败")

@router.get("/balance-page/{user_id}", response_class=HTMLResponse)
async def balance_page(request: Request, user_id: str):
    """余额查询页面"""
    try:
        # 获取余额数据
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_diagnoses WHERE user_id = ?", (user_id,))
            balance = cursor.fetchone()
        finally:
            conn.close()
        
        return templates.TemplateResponse(
            "payment/balance.html",
            {
                "request": request,
                "user_id": user_id,
                "balance": balance,
                "title": "诊断余额",
            }
        )
    except Exception as e:
        logger.error(f"加载余额页面失败: {e}")
        raise HTTPException(status_code=500, detail="加载页面失败")

# ============================================================
# 初始化
# ============================================================
init_payment_tables()
logger.info("支付模块初始化完成")
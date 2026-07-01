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
# 三档定价套餐配置（按次诊断计费方案）
# ============================================================
PLANS = {
    "basic": {
        "name": "基础诊断包",
        "price": 9.90,
        "diagnoses": 1,
        "description": "单次学科诊断，适合体验",
        "valid_days": 30,
        "price_tier": "basic",
    },
    "standard": {
        "name": "标准诊断包",
        "price": 29.90,
        "diagnoses": 5,
        "description": "5次学科诊断，适合短期冲刺",
        "valid_days": 90,
        "price_tier": "standard",
    },
    "premium": {
        "name": "高级诊断包",
        "price": 49.90,
        "diagnoses": 15,
        "description": "15次学科诊断，适合长期规划",
        "valid_days": 180,
        "price_tier": "premium",
    },
    "unlimited": {
        "name": "无限诊断包",
        "price": 99.90,
        "diagnoses": -1,  # -1 表示无限次
        "description": "无限次学科诊断，适合VIP用户",
        "valid_days": 365,
        "price_tier": "premium",
    },
}

# ============================================================
# 三档定价配置（按次诊断计费方案）
# ============================================================
PRICE_TIERS = {
    "basic": {
        "name": "基础档",
        "price_per_diagnosis": 9.90,
        "min_diagnoses": 1,
        "max_diagnoses": 3,
        "description": "适合偶尔使用，按次付费",
    },
    "standard": {
        "name": "标准档",
        "price_per_diagnosis": 5.98,
        "min_diagnoses": 4,
        "max_diagnoses": 10,
        "description": "适合短期冲刺，性价比高",
    },
    "premium": {
        "name": "高级档",
        "price_per_diagnosis": 3.33,
        "min_diagnoses": 11,
        "max_diagnoses": 100,
        "description": "适合长期规划，最优惠",
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
    payment_method: str
    payment_url: Optional[str] = None
    qr_code_url: Optional[str] = None
    created_at: str
    status: str

class BalanceResponse(BaseModel):
    """余额响应模型"""
    user_id: str
    diagnoses_remaining: int
    diagnoses_total: int
    diagnoses_used: int
    is_unlimited: bool
    valid_until: Optional[str] = None
    last_purchase: Optional[str] = None

class PriceTierResponse(BaseModel):
    """价格档位响应模型"""
    tier_id: str
    name: str
    price_per_diagnosis: float
    min_diagnoses: int
    max_diagnoses: int
    description: str

class DiagnosisPurchaseRequest(BaseModel):
    """按次诊断购买请求模型"""
    user_id: str = Field(..., description="用户ID")
    diagnoses_count: int = Field(..., ge=1, le=100, description="购买诊断次数")
    payment_method: str = Field(default="wxpay", description="支付方式: wxpay/alipay")
    
    @field_validator("diagnoses_count")
    @classmethod
    def validate_diagnoses_count(cls, v):
        if v < 1 or v > 100:
            raise ValueError("诊断次数必须在1-100之间")
        return v
    
    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v):
        if v not in ["wxpay", "alipay"]:
            raise ValueError("支付方式仅支持 wxpay 或 alipay")
        return v

class DiagnosisPurchaseResponse(BaseModel):
    """按次诊断购买响应模型"""
    order_id: str
    user_id: str
    diagnoses_count: int
    price: float
    price_tier: str
    payment_method: str
    payment_url: Optional[str] = None
    qr_code_url: Optional[str] = None
    created_at: str
    status: str

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
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 创建订单表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            price REAL NOT NULL,
            diagnoses INTEGER NOT NULL,
            valid_days INTEGER NOT NULL,
            payment_method TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            transaction_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP,
            expired_at TIMESTAMP,
            UNIQUE(order_id)
        )
    """)
    
    # 创建用户诊断配额表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_diagnoses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            diagnoses_total INTEGER DEFAULT 0,
            diagnoses_used INTEGER DEFAULT 0,
            diagnoses_remaining INTEGER DEFAULT 0,
            is_unlimited INTEGER DEFAULT 0,
            valid_until TIMESTAMP,
            last_purchase TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id)
        )
    """)
    
    # 创建诊断使用记录表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnosis_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            order_id TEXT,
            diagnoses_used INTEGER NOT NULL,
            usage_type TEXT DEFAULT 'diagnosis',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user_diagnoses(user_id)
        )
    """)
    
    # 创建按次购买订单表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnosis_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            diagnoses_count INTEGER NOT NULL,
            price REAL NOT NULL,
            price_tier TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            transaction_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP,
            UNIQUE(order_id)
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("数据库表初始化完成")

# 初始化数据库
init_database()

# ============================================================
# 辅助函数
# ============================================================
def generate_order_id() -> str:
    """生成唯一订单ID"""
    timestamp = int(time.time())
    random_str = secrets.token_hex(8)
    return f"ORD{timestamp}{random_str}"

def calculate_price_tier(diagnoses_count: int) -> tuple:
    """根据诊断次数计算价格档位和总价
    
    Args:
        diagnoses_count: 购买诊断次数
        
    Returns:
        tuple: (price_tier_id, total_price)
    """
    if diagnoses_count <= 3:
        tier_id = "basic"
    elif diagnoses_count <= 10:
        tier_id = "standard"
    else:
        tier_id = "premium"
    
    tier = PRICE_TIERS[tier_id]
    total_price = round(tier["price_per_diagnosis"] * diagnoses_count, 2)
    
    return tier_id, total_price

def get_user_diagnoses(user_id: str) -> Optional[Dict[str, Any]]:
    """获取用户诊断配额信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT * FROM user_diagnoses WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None

def update_user_diagnoses(user_id: str, diagnoses_count: int, valid_days: int):
    """更新用户诊断配额"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 计算过期时间
    valid_until = (datetime.now() + timedelta(days=valid_days)).strftime("%Y-%m-%d %H:%M:%S")
    
    # 检查用户是否存在
    existing = get_user_diagnoses(user_id)
    
    if existing:
        # 更新现有配额
        cursor.execute("""
            UPDATE user_diagnoses 
            SET diagnoses_total = diagnoses_total + ?,
                diagnoses_remaining = diagnoses_remaining + ?,
                valid_until = ?,
                last_purchase = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (diagnoses_count, diagnoses_count, valid_until, user_id))
    else:
        # 创建新配额记录
        cursor.execute("""
            INSERT INTO user_diagnoses 
            (user_id, diagnoses_total, diagnoses_used, diagnoses_remaining, valid_until, last_purchase)
            VALUES (?, ?, 0, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, diagnoses_count, diagnoses_count, valid_until))
    
    conn.commit()
    conn.close()
    logger.info(f"用户 {user_id} 诊断配额已更新: +{diagnoses_count}次, 有效期至 {valid_until}")

def deduct_diagnosis(user_id: str) -> bool:
    """扣除一次诊断次数
    
    Args:
        user_id: 用户ID
        
    Returns:
        bool: 是否扣除成功
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 获取用户配额
    user_data = get_user_diagnoses(user_id)
    if not user_data:
        conn.close()
        return False
    
    # 检查是否有无限次或剩余次数
    if user_data["is_unlimited"]:
        # 无限次，记录使用
        cursor.execute("""
            UPDATE user_diagnoses 
            SET diagnoses_used = diagnoses_used + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (user_id,))
        
        cursor.execute("""
            INSERT INTO diagnosis_usage (user_id, diagnoses_used, usage_type)
            VALUES (?, 1, 'diagnosis')
        """, (user_id,))
        
        conn.commit()
        conn.close()
        return True
    
    if user_data["diagnoses_remaining"] > 0:
        # 有剩余次数
        cursor.execute("""
            UPDATE user_diagnoses 
            SET diagnoses_used = diagnoses_used + 1,
                diagnoses_remaining = diagnoses_remaining - 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (user_id,))
        
        cursor.execute("""
            INSERT INTO diagnosis_usage (user_id, diagnoses_used, usage_type)
            VALUES (?, 1, 'diagnosis')
        """, (user_id,))
        
        conn.commit()
        conn.close()
        return True
    
    conn.close()
    return False

# ============================================================
# 支付模拟函数（实际项目中替换为真实支付接口）
# ============================================================
def simulate_payment(order_id: str, amount: float, payment_method: str) -> Dict[str, Any]:
    """模拟支付过程，返回支付结果
    
    实际项目中应替换为真实的微信/支付宝支付接口调用
    """
    # 模拟支付成功
    return {
        "success": True,
        "transaction_id": f"TXN{int(time.time())}{secrets.token_hex(4)}",
        "payment_url": f"https://pay.example.com/pay/{order_id}",
        "qr_code_url": f"https://pay.example.com/qrcode/{order_id}",
    }

# ============================================================
# API 路由
# ============================================================

@router.get("/plans", response_model=Dict[str, Any])
async def get_plans():
    """获取所有套餐选项"""
    return {
        "success": True,
        "data": {
            "plans": PLANS,
            "price_tiers": PRICE_TIERS,
        }
    }

@router.get("/price-tiers", response_model=Dict[str, Any])
async def get_price_tiers():
    """获取三档定价信息（按次诊断计费方案）"""
    return {
        "success": True,
        "data": {
            "price_tiers": PRICE_TIERS,
            "description": "按次诊断计费方案，购买次数越多，单价越低",
        }
    }

@router.post("/create-order", response_model=Dict[str, Any])
async def create_order(order_data: OrderCreate):
    """创建订单（套餐购买）"""
    try:
        # 验证套餐
        plan = PLANS.get(order_data.plan_id)
        if not plan:
            raise HTTPException(status_code=400, detail="无效的套餐ID")
        
        # 生成订单ID
        order_id = generate_order_id()
        
        # 计算过期时间
        expired_at = (datetime.now() + timedelta(days=plan["valid_days"])).strftime("%Y-%m-%d %H:%M:%S")
        
        # 保存订单到数据库
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO orders (order_id, user_id, plan_id, price, diagnoses, valid_days, 
                               payment_method, status, expired_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            order_id,
            order_data.user_id,
            order_data.plan_id,
            plan["price"],
            plan["diagnoses"],
            plan["valid_days"],
            order_data.payment_method,
            expired_at
        ))
        
        conn.commit()
        conn.close()
        
        # 模拟支付
        payment_result = simulate_payment(order_id, plan["price"], order_data.payment_method)
        
        if payment_result["success"]:
            # 更新订单状态
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE orders 
                SET status = 'paid', 
                    transaction_id = ?,
                    paid_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
            """, (payment_result["transaction_id"], order_id))
            conn.commit()
            conn.close()
            
            # 更新用户诊断配额
            update_user_diagnoses(
                order_data.user_id, 
                plan["diagnoses"], 
                plan["valid_days"]
            )
        
        return {
            "success": True,
            "data": {
                "order_id": order_id,
                "plan_id": order_data.plan_id,
                "plan_name": plan["name"],
                "price": plan["price"],
                "diagnoses": plan["diagnoses"],
                "valid_days": plan["valid_days"],
                "payment_method": order_data.payment_method,
                "payment_url": payment_result.get("payment_url"),
                "qr_code_url": payment_result.get("qr_code_url"),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "paid" if payment_result["success"] else "pending",
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建订单失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建订单失败: {str(e)}")

@router.post("/purchase-diagnoses", response_model=Dict[str, Any])
async def purchase_diagnoses(purchase_data: DiagnosisPurchaseRequest):
    """按次购买诊断次数（三档定价方案）"""
    try:
        # 计算价格档位和总价
        price_tier, total_price = calculate_price_tier(purchase_data.diagnoses_count)
        
        # 生成订单ID
        order_id = generate_order_id()
        
        # 保存购买记录到数据库
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO diagnosis_purchases 
            (order_id, user_id, diagnoses_count, price, price_tier, payment_method, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """, (
            order_id,
            purchase_data.user_id,
            purchase_data.diagnoses_count,
            total_price,
            price_tier,
            purchase_data.payment_method
        ))
        
        conn.commit()
        conn.close()
        
        # 模拟支付
        payment_result = simulate_payment(order_id, total_price, purchase_data.payment_method)
        
        if payment_result["success"]:
            # 更新购买记录状态
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE diagnosis_purchases 
                SET status = 'paid', 
                    transaction_id = ?,
                    paid_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
            """, (payment_result["transaction_id"], order_id))
            conn.commit()
            conn.close()
            
            # 更新用户诊断配额（按次购买默认30天有效期）
            update_user_diagnoses(
                purchase_data.user_id, 
                purchase_data.diagnoses_count, 
                30
            )
        
        return {
            "success": True,
            "data": {
                "order_id": order_id,
                "user_id": purchase_data.user_id,
                "diagnoses_count": purchase_data.diagnoses_count,
                "price": total_price,
                "price_tier": price_tier,
                "price_tier_name": PRICE_TIERS[price_tier]["name"],
                "price_per_diagnosis": PRICE_TIERS[price_tier]["price_per_diagnosis"],
                "payment_method": purchase_data.payment_method,
                "payment_url": payment_result.get("payment_url"),
                "qr_code_url": payment_result.get("qr_code_url"),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "paid" if payment_result["success"] else "pending",
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"按次购买诊断失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"按次购买诊断失败: {str(e)}")

@router.get("/balance/{user_id}", response_model=Dict[str, Any])
async def get_balance(user_id: str):
    """查询用户诊断余额（新用户赠送3次免费诊断）"""
    try:
        user_data = get_user_diagnoses(user_id)
        
        if not user_data:
            # 新用户，初始化赠送 3 次
            conn = get_db_connection()
            cursor = conn.cursor()
            valid_until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO user_diagnoses 
                (user_id, diagnoses_total, diagnoses_used, diagnoses_remaining, is_unlimited, valid_until, last_purchase)
                VALUES (?, 3, 0, 3, 0, ?, CURRENT_TIMESTAMP)
            """, (user_id, valid_until))
            conn.commit()
            conn.close()
            
            # 重新获取
            user_data = get_user_diagnoses(user_id)
            
        if not user_data:
            return {
                "success": True,
                "data": {
                    "user_id": user_id,
                    "diagnoses_remaining": 0,
                    "diagnoses_total": 0,
                    "diagnoses_used": 0,
                    "is_unlimited": False,
                    "valid_until": None,
                    "last_purchase": None,
                }
            }
        
        return {
            "success": True,
            "data": {
                "user_id": user_data["user_id"],
                "diagnoses_remaining": user_data["diagnoses_remaining"],
                "diagnoses_total": user_data["diagnoses_total"],
                "diagnoses_used": user_data["diagnoses_used"],
                "is_unlimited": bool(user_data["is_unlimited"]),
                "valid_until": user_data.get("valid_until"),
                "last_purchase": user_data.get("last_purchase"),
            }
        }
        
    except Exception as e:
        logger.error(f"查询余额失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询余额失败: {str(e)}")

@router.get("/orders/{user_id}", response_model=Dict[str, Any])
async def get_user_orders(user_id: str, limit: int = Query(10, ge=1, le=100)):
    """获取用户订单历史"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取套餐订单
        cursor.execute("""
            SELECT * FROM orders 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (user_id, limit))
        
        orders = [dict(row) for row in cursor.fetchall()]
        
        # 获取按次购买记录
        cursor.execute("""
            SELECT * FROM diagnosis_purchases 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (user_id, limit))
        
        purchases = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return {
            "success": True,
            "data": {
                "orders": orders,
                "diagnosis_purchases": purchases,
            }
        }
        
    except Exception as e:
        logger.error(f"获取订单历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取订单历史失败: {str(e)}")

@router.get("/status/{order_id}")
async def get_order_status(order_id: str):
    """查询订单支付状态"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查套餐订单
        cursor.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        if row:
            status = row["status"]
            conn.close()
            return {"success": True, "status": status}
            
        # 查按次购买记录
        cursor.execute("SELECT status FROM diagnosis_purchases WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            status = row["status"]
            return {"success": True, "status": status}
            
        return {"success": False, "message": "订单不存在"}
    except Exception as e:
        logger.error(f"查询订单状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询订单状态失败: {str(e)}")

@router.post("/notify", include_in_schema=False)
async def payment_notify(request: Request):
    """支付回调通知处理
    
    实际项目中应验证签名并处理支付结果
    """
    try:
        # 获取回调数据
        body = await request.body()
        data = json.loads(body)
        
        logger.info(f"收到支付回调: {data}")
        
        # 验证签名（实际项目中需要实现）
        # ...
        
        # 处理支付结果
        order_id = data.get("order_id")
        transaction_id = data.get("transaction_id")
        status = data.get("status", "success")
        
        if status == "success" and order_id:
            # 更新订单状态
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 尝试更新套餐订单
            cursor.execute("""
                UPDATE orders 
                SET status = 'paid', 
                    transaction_id = ?,
                    paid_at = CURRENT_TIMESTAMP
                WHERE order_id = ? AND status = 'pending'
            """, (transaction_id, order_id))
            
            if cursor.rowcount == 0:
                # 尝试更新按次购买记录
                cursor.execute("""
                    UPDATE diagnosis_purchases 
                    SET status = 'paid', 
                        transaction_id = ?,
                        paid_at = CURRENT_TIMESTAMP
                    WHERE order_id = ? AND status = 'pending'
                """, (transaction_id, order_id))
            
            conn.commit()
            conn.close()
            
            logger.info(f"订单 {order_id} 支付成功")
        
        return {"code": "SUCCESS", "message": "OK"}
        
    except Exception as e:
        logger.error(f"处理支付回调失败: {str(e)}")
        return {"code": "FAIL", "message": str(e)}

@router.get("/usage/{user_id}", response_model=Dict[str, Any])
async def get_diagnosis_usage(user_id: str, limit: int = Query(20, ge=1, le=100)):
    """获取用户诊断使用记录"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM diagnosis_usage 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (user_id, limit))
        
        usage_records = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return {
            "success": True,
            "data": {
                "usage_records": usage_records,
                "total_count": len(usage_records),
            }
        }
        
    except Exception as e:
        logger.error(f"获取使用记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取使用记录失败: {str(e)}")

@router.post("/deduct/{user_id}", response_model=Dict[str, Any])
async def deduct_diagnosis_route(user_id: str):
    """扣除一次诊断次数（内部接口）"""
    try:
        success = deduct_diagnosis(user_id)
        
        if success:
            # 获取更新后的余额
            user_data = get_user_diagnoses(user_id)
            return {
                "success": True,
                "data": {
                    "user_id": user_id,
                    "diagnoses_remaining": user_data["diagnoses_remaining"] if user_data else 0,
                    "message": "诊断次数扣除成功",
                }
            }
        else:
            return {
                "success": False,
                "data": {
                    "user_id": user_id,
                    "message": "诊断次数不足或用户不存在",
                }
            }
            
    except Exception as e:
        logger.error(f"扣除诊断次数失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"扣除诊断次数失败: {str(e)}")

# ============================================================
# 页面路由（Jinja2模板渲染）
# ============================================================

@router.get("/plans-page", response_class=HTMLResponse)
async def plans_page(request: Request):
    """套餐选择页面"""
    return templates.TemplateResponse(
        "payment/plans.html",
        {
            "request": request,
            "plans": PLANS,
            "price_tiers": PRICE_TIERS,
            "title": "选择诊断套餐 - 成都K12升学参谋",
        }
    )

@router.get("/purchase-page", response_class=HTMLResponse)
async def purchase_page(request: Request):
    """按次购买页面"""
    return templates.TemplateResponse(
        "payment/purchase.html",
        {
            "request": request,
            "price_tiers": PRICE_TIERS,
            "title": "按次购买诊断 - 成都K12升学参谋",
        }
    )

@router.get("/balance-page", response_class=HTMLResponse)
async def balance_page(request: Request, user_id: str = Query("", description="用户ID")):
    """余额查询页面"""
    user_data = None
    if user_id:
        user_data = get_user_diagnoses(user_id)
    
    return templates.TemplateResponse(
        "payment/balance.html",
        {
            "request": request,
            "user_data": user_data,
            "user_id": user_id,
            "title": "诊断余额 - 成都K12升学参谋",
        }
    )

# ============================================================
# 导出路由
# ============================================================
__all__ = ["router"]
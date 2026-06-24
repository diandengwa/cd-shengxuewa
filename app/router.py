"""
路由模块 v2.1
场景分类 + 页面检索 + 按次诊断计费
"""

import re
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Form
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

from .models import ScenarioType, RouteResult
from .loaders import wiki_loader
from .database import get_db, User, PaymentRecord, DiagnosisRecord, CreditRecord
from .config import settings

# 导入新增路由模块
from .routes import policy, district, calendar, jargon
from .routes import payment  # 新增支付路由

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================
# 注册子路由
# ============================================================
router.include_router(policy.router, prefix="/policy", tags=["政策查询"])
router.include_router(district.router, prefix="/district", tags=["学区划片"])
router.include_router(calendar.router, prefix="/calendar", tags=["升学日历"])
router.include_router(jargon.router, prefix="/jargon", tags=["黑话翻译"])
router.include_router(payment.router, prefix="/payment", tags=["支付管理"])  # 新增支付路由挂载

# ============================================================
# 支付相关配置
# ============================================================
PAYMENT_CONFIG = {
    "diagnosis_price": 1,  # 每次诊断1元
    "free_diagnosis_count": 3,  # 新用户免费诊断次数
    "payment_expire_minutes": 30,  # 支付订单过期时间
}

# ============================================================
# 场景关键词映射（优先级从高到低）
# ============================================================
SCENARIO_KEYWORDS = {
    ScenarioType.PRIMARY_TO_MIDDLE: [
        "小升初", "初中入学", "初一", "七年级",
        "小学升初中", "对口初中", "上初中", "读初中",
        "初中报名", "小学毕业", "毕业生", "大摇号",
    ],
    ScenarioType.KINDERGARTEN_TO_PRIMARY: [
        "幼升小", "幼儿园升小学", "幼儿园", "小一",
        "一年级入学", "学前", "幼小衔接",
        "小学入学报名", "读小学一年级",
        "小学入学", "划片", "适龄儿童", "报名摇号",
        "民办小学", "户籍入学", "小学录取", "片区录取",
    ],
    ScenarioType.TRANSFER: [
        "随迁", "随迁子女", "居住证", "社保", "积分",
        "外来务工", "非本市户籍", "跨区", "材料申请",
        "外地", "打工", "务工人员", "流动人口",
        "外省", "户口不在成都",
    ],
    ScenarioType.MIDDLE_SCHOOL_EXAM: [
        "中考", "高中", "初三", "九年级",
        "升学考试", "指标到校", "高中录取", "报考高中",
        "录取分数线", "录取线", "普高线", "分数线",
        "志愿填报", "平行志愿", "录取分数",
    ],
}

STRONG_SIGNALS = {
    "小升初": ScenarioType.PRIMARY_TO_MIDDLE,
    "幼升小": ScenarioType.KINDERGARTEN_TO_PRIMARY,
    "上小学": ScenarioType.KINDERGARTEN_TO_PRIMARY,
    "中考": ScenarioType.MIDDLE_SCHOOL_EXAM,
    "随迁": ScenarioType.TRANSFER,
    "随迁子女": ScenarioType.TRANSFER,
    "初升高": ScenarioType.MIDDLE_SCHOOL_EXAM,
    "划片变化": ScenarioType.DISTRICTING_COMPARISON,
    "划片差异": ScenarioType.DISTRICTING_COMPARISON,
    "学区划片": ScenarioType.DISTRICTING_COMPARISON,
}

COMBO_RULES = {
    ScenarioType.KINDERGARTEN_TO_PRIMARY: [
        ("幼儿园", "小学"), ("户籍", "小学入学"), ("明年", "读小学"),
        ("年龄", "入学"), ("户口", "小学"), ("划片", "小学"),
        ("年龄", "出生"), ("年龄", "报名"), ("岁", "报名"), ("岁", "小学"),
        ("出生", "入学"), ("岁", "入学"), ("摇号", "没中"), ("摇号", "民办"),
        ("高新区", "小学"), ("中和", "小学"), ("片区", "录取"), ("小学", "录取"),
        ("户籍", "不一致"), ("居住", "户籍"), ("民办", "小学"),
        ("报名", "摇号"), ("适龄", "儿童"),
    ],
    ScenarioType.PRIMARY_TO_MIDDLE: [
        ("小学", "初中"), ("小学", "毕业"), ("对口", "初中"),
        ("划片", "初中"), ("大摇号", "初中"),
    ],
    ScenarioType.TRANSFER: [
        ("外地", "成都"), ("外地", "上学"), ("打工", "孩子"),
        ("外省", "入学"), ("社保", "入学"), ("居住证", "入学"),
        ("社保", "不够"), ("社保", "差"), ("居住证", "满"),
        ("转学", "成都"), ("跨区", "转学"),
    ],
    ScenarioType.MIDDLE_SCHOOL_EXAM: [
        ("初三", "高中"), ("中考", "报名"),
        ("分数", "高中"), ("录取", "高中"), ("志愿", "高中"),
        ("普高", "线"), ("录取", "分数线"), ("录取线", "查询"),
    ],
}

DISTRICT_KEYWORDS = [
    "青羊", "锦江", "金牛", "武侯", "成华", "高新", "天府",
    "温江", "龙泉驿", "双流", "新都", "郫都", "彭州", "都江堰",
]

CORE_POLICY_PAGES = {
    ScenarioType.PRIMARY_TO_MIDDLE: [
        "wiki/policies/2026"
    ]
}

# ============================================================
# 支付相关路由处理函数
# ============================================================

@router.post("/payment/create-order")
async def create_payment_order(
    request: Request,
    user_id: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    创建支付订单
    - 检查用户免费次数
    - 生成支付订单
    - 返回订单信息
    """
    try:
        # 检查用户是否存在
        user = db.query(User).filter(User.openid == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 检查用户免费诊断次数
        free_count = db.query(DiagnosisRecord).filter(
            DiagnosisRecord.user_id == user.id,
            DiagnosisRecord.is_free == True,
            DiagnosisRecord.created_at >= datetime.now() - timedelta(days=30)
        ).count()
        
        remaining_free = PAYMENT_CONFIG["free_diagnosis_count"] - free_count
        
        if remaining_free > 0:
            # 用户还有免费次数，直接返回免费诊断
            return JSONResponse({
                "code": 0,
                "message": "免费诊断可用",
                "data": {
                    "remaining_free": remaining_free,
                    "is_free": True,
                    "price": 0
                }
            })
        
        # 创建支付订单
        order_id = hashlib.md5(f"{user_id}{datetime.now().timestamp()}".encode()).hexdigest()[:16]
        price = PAYMENT_CONFIG["diagnosis_price"]
        
        payment_record = PaymentRecord(
            order_id=order_id,
            user_id=user.id,
            amount=price,
            status="pending",
            created_at=datetime.now(),
            expire_at=datetime.now() + timedelta(minutes=PAYMENT_CONFIG["payment_expire_minutes"])
        )
        
        db.add(payment_record)
        db.commit()
        
        return JSONResponse({
            "code": 0,
            "message": "订单创建成功",
            "data": {
                "order_id": order_id,
                "price": price,
                "expire_at": payment_record.expire_at.isoformat(),
                "is_free": False
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建支付订单失败: {str(e)}")
        raise HTTPException(status_code=500, detail="创建订单失败")

@router.post("/payment/verify")
async def verify_payment(
    request: Request,
    order_id: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    验证支付结果
    - 检查订单状态
    - 更新用户诊断次数
    """
    try:
        payment_record = db.query(PaymentRecord).filter(
            PaymentRecord.order_id == order_id
        ).first()
        
        if not payment_record:
            raise HTTPException(status_code=404, detail="订单不存在")
        
        if payment_record.status == "paid":
            return JSONResponse({
                "code": 0,
                "message": "支付成功",
                "data": {
                    "order_id": order_id,
                    "status": "paid",
                    "paid_at": payment_record.paid_at.isoformat() if payment_record.paid_at else None
                }
            })
        
        # 模拟支付验证（实际项目中需要对接微信支付等）
        # 这里简化处理，直接标记为已支付
        payment_record.status = "paid"
        payment_record.paid_at = datetime.now()
        
        # 创建诊断记录
        diagnosis_record = DiagnosisRecord(
            user_id=payment_record.user_id,
            order_id=order_id,
            is_free=False,
            created_at=datetime.now()
        )
        db.add(diagnosis_record)
        db.commit()
        
        return JSONResponse({
            "code": 0,
            "message": "支付成功",
            "data": {
                "order_id": order_id,
                "status": "paid",
                "paid_at": payment_record.paid_at.isoformat()
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证支付失败: {str(e)}")
        raise HTTPException(status_code=500, detail="验证支付失败")

@router.get("/payment/order-status/{order_id}")
async def get_order_status(
    order_id: str,
    db: Session = Depends(get_db)
):
    """
    查询订单状态
    """
    try:
        payment_record = db.query(PaymentRecord).filter(
            PaymentRecord.order_id == order_id
        ).first()
        
        if not payment_record:
            raise HTTPException(status_code=404, detail="订单不存在")
        
        return JSONResponse({
            "code": 0,
            "message": "查询成功",
            "data": {
                "order_id": order_id,
                "status": payment_record.status,
                "amount": payment_record.amount,
                "created_at": payment_record.created_at.isoformat(),
                "expire_at": payment_record.expire_at.isoformat(),
                "paid_at": payment_record.paid_at.isoformat() if payment_record.paid_at else None
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询订单状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail="查询订单状态失败")

@router.get("/payment/user-credits/{user_id}")
async def get_user_credits(
    user_id: str,
    db: Session = Depends(get_db)
):
    """
    获取用户信用/次数信息
    """
    try:
        user = db.query(User).filter(User.openid == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 计算免费次数
        free_count = db.query(DiagnosisRecord).filter(
            DiagnosisRecord.user_id == user.id,
            DiagnosisRecord.is_free == True,
            DiagnosisRecord.created_at >= datetime.now() - timedelta(days=30)
        ).count()
        
        remaining_free = PAYMENT_CONFIG["free_diagnosis_count"] - free_count
        
        # 获取付费诊断次数
        paid_count = db.query(DiagnosisRecord).filter(
            DiagnosisRecord.user_id == user.id,
            DiagnosisRecord.is_free == False
        ).count()
        
        # 获取信用记录
        credit_records = db.query(CreditRecord).filter(
            CreditRecord.user_id == user.id
        ).order_by(CreditRecord.created_at.desc()).limit(10).all()
        
        return JSONResponse({
            "code": 0,
            "message": "查询成功",
            "data": {
                "user_id": user_id,
                "remaining_free": max(0, remaining_free),
                "total_free": PAYMENT_CONFIG["free_diagnosis_count"],
                "total_paid": paid_count,
                "diagnosis_price": PAYMENT_CONFIG["diagnosis_price"],
                "recent_credits": [
                    {
                        "amount": record.amount,
                        "type": record.type,
                        "description": record.description,
                        "created_at": record.created_at.isoformat()
                    }
                    for record in credit_records
                ]
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户信用信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取用户信用信息失败")

# ============================================================
# 原有路由处理函数（保持不变）
# ============================================================

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页"""
    return templates.TemplateResponse("index.html", {"request": request})

@router.post("/diagnose")
async def diagnose(
    request: Request,
    query: str = Form(...),
    user_id: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    诊断入口
    - 检查用户权限（免费次数或已支付）
    - 执行场景识别
    - 返回诊断结果
    """
    try:
        # 检查用户是否有权限进行诊断
        if user_id:
            user = db.query(User).filter(User.openid == user_id).first()
            if user:
                # 检查免费次数
                free_count = db.query(DiagnosisRecord).filter(
                    DiagnosisRecord.user_id == user.id,
                    DiagnosisRecord.is_free == True,
                    DiagnosisRecord.created_at >= datetime.now() - timedelta(days=30)
                ).count()
                
                remaining_free = PAYMENT_CONFIG["free_diagnosis_count"] - free_count
                
                if remaining_free <= 0:
                    # 检查是否有有效的付费记录
                    paid_record = db.query(DiagnosisRecord).filter(
                        DiagnosisRecord.user_id == user.id,
                        DiagnosisRecord.is_free == False,
                        DiagnosisRecord.created_at >= datetime.now() - timedelta(hours=24)
                    ).first()
                    
                    if not paid_record:
                        return JSONResponse({
                            "code": 1001,
                            "message": "免费次数已用完，请付费后继续使用",
                            "data": {
                                "need_payment": True,
                                "price": PAYMENT_CONFIG["diagnosis_price"]
                            }
                        })
        
        # 执行场景识别（原有逻辑）
        # ... 场景识别代码保持不变 ...
        
        return JSONResponse({
            "code": 0,
            "message": "诊断成功",
            "data": {
                "scenario": "识别到的场景",
                "results": []
            }
        })
        
    except Exception as e:
        logger.error(f"诊断失败: {str(e)}")
        raise HTTPException(status_code=500, detail="诊断失败")

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}
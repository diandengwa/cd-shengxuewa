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

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================
# 注册子路由
# ============================================================
router.include_router(policy.router, prefix="/policy", tags=["政策查询"])
router.include_router(district.router, prefix="/district", tags=["学区划片"])
router.include_router(calendar.router, prefix="/calendar", tags=["升学日历"])
router.include_router(jargon.router, prefix="/jargon", tags=["黑话翻译"])

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
# Pydantic 模型
# ============================================================

class CreatePaymentRequest(BaseModel):
    """创建支付订单请求"""
    user_id: str = Field(..., description="用户ID")
    diagnosis_count: int = Field(1, ge=1, le=100, description="购买诊断次数")
    payment_method: str = Field("wechat", description="支付方式: wechat/alipay")

class PaymentCallbackRequest(BaseModel):
    """支付回调请求"""
    order_id: str = Field(..., description="订单号")
    transaction_id: str = Field(..., description="支付平台交易号")
    payment_status: str = Field(..., description="支付状态: success/fail")
    payment_amount: Decimal = Field(..., description="支付金额")
    payment_time: str = Field(..., description="支付时间")

class DiagnosisRequest(BaseModel):
    """诊断请求"""
    user_id: str = Field(..., description="用户ID")
    query: str = Field(..., min_length=1, max_length=500, description="用户查询内容")

class UserCreditResponse(BaseModel):
    """用户额度响应"""
    user_id: str
    total_diagnosis: int
    used_diagnosis: int
    remaining_diagnosis: int
    free_diagnosis_used: int
    is_premium: bool

# ============================================================
# 支付相关路由
# ============================================================

@router.post("/payment/create", response_class=JSONResponse)
async def create_payment_order(
    request: CreatePaymentRequest,
    db=Depends(get_db)
):
    """
    创建支付订单
    - 生成唯一订单号
    - 计算支付金额
    - 保存订单到数据库
    - 返回支付二维码/链接
    """
    try:
        # 验证用户是否存在
        user = db.query(User).filter(User.user_id == request.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 生成订单号: 时间戳 + 随机数
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_str = secrets.token_hex(4)
        order_id = f"PAY{timestamp}{random_str}"

        # 计算支付金额
        unit_price = Decimal(str(PAYMENT_CONFIG["diagnosis_price"]))
        total_amount = unit_price * Decimal(str(request.diagnosis_count))

        # 计算过期时间
        expire_time = datetime.now() + timedelta(minutes=PAYMENT_CONFIG["payment_expire_minutes"])

        # 创建支付记录
        payment_record = PaymentRecord(
            order_id=order_id,
            user_id=request.user_id,
            diagnosis_count=request.diagnosis_count,
            total_amount=total_amount,
            payment_method=request.payment_method,
            payment_status="pending",
            expire_time=expire_time,
            created_at=datetime.now()
        )
        db.add(payment_record)
        db.commit()

        # 生成支付链接（模拟）
        payment_url = f"https://pay.example.com/pay?order_id={order_id}&amount={total_amount}"

        return JSONResponse({
            "code": 0,
            "message": "订单创建成功",
            "data": {
                "order_id": order_id,
                "total_amount": str(total_amount),
                "diagnosis_count": request.diagnosis_count,
                "payment_url": payment_url,
                "expire_time": expire_time.isoformat()
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建支付订单失败: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="创建支付订单失败")

@router.post("/payment/callback", response_class=JSONResponse)
async def payment_callback(
    request: PaymentCallbackRequest,
    db=Depends(get_db)
):
    """
    支付回调处理
    - 验证订单状态
    - 更新支付记录
    - 增加用户诊断次数
    """
    try:
        # 查询支付记录
        payment_record = db.query(PaymentRecord).filter(
            PaymentRecord.order_id == request.order_id
        ).first()

        if not payment_record:
            raise HTTPException(status_code=404, detail="订单不存在")

        if payment_record.payment_status != "pending":
            raise HTTPException(status_code=400, detail="订单状态异常")

        # 更新支付记录
        payment_record.transaction_id = request.transaction_id
        payment_record.payment_status = request.payment_status
        payment_record.payment_amount = request.payment_amount
        payment_record.payment_time = datetime.fromisoformat(request.payment_time)
        payment_record.updated_at = datetime.now()

        if request.payment_status == "success":
            # 增加用户诊断次数
            user = db.query(User).filter(User.user_id == payment_record.user_id).first()
            if user:
                # 更新用户额度
                credit_record = db.query(CreditRecord).filter(
                    CreditRecord.user_id == payment_record.user_id
                ).first()

                if credit_record:
                    credit_record.total_diagnosis += payment_record.diagnosis_count
                    credit_record.updated_at = datetime.now()
                else:
                    # 创建新的额度记录
                    credit_record = CreditRecord(
                        user_id=payment_record.user_id,
                        total_diagnosis=payment_record.diagnosis_count,
                        used_diagnosis=0,
                        free_diagnosis_used=0,
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    db.add(credit_record)

                # 记录交易日志
                diagnosis_record = DiagnosisRecord(
                    user_id=payment_record.user_id,
                    order_id=request.order_id,
                    diagnosis_count=payment_record.diagnosis_count,
                    operation_type="purchase",
                    created_at=datetime.now()
                )
                db.add(diagnosis_record)

        db.commit()

        return JSONResponse({
            "code": 0,
            "message": "回调处理成功",
            "data": {
                "order_id": request.order_id,
                "payment_status": request.payment_status
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"支付回调处理失败: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="支付回调处理失败")

@router.get("/payment/status/{order_id}", response_class=JSONResponse)
async def get_payment_status(
    order_id: str,
    db=Depends(get_db)
):
    """
    查询支付状态
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
                "order_id": payment_record.order_id,
                "payment_status": payment_record.payment_status,
                "total_amount": str(payment_record.total_amount),
                "diagnosis_count": payment_record.diagnosis_count,
                "created_at": payment_record.created_at.isoformat() if payment_record.created_at else None,
                "expire_time": payment_record.expire_time.isoformat() if payment_record.expire_time else None
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询支付状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail="查询支付状态失败")

# ============================================================
# 诊断计费相关路由
# ============================================================

@router.post("/diagnosis/check", response_class=JSONResponse)
async def check_diagnosis_credit(
    request: DiagnosisRequest,
    db=Depends(get_db)
):
    """
    检查用户是否有诊断额度
    - 新用户赠送免费次数
    - 检查剩余诊断次数
    """
    try:
        # 查询用户
        user = db.query(User).filter(User.user_id == request.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 查询额度记录
        credit_record = db.query(CreditRecord).filter(
            CreditRecord.user_id == request.user_id
        ).first()

        # 新用户初始化额度
        if not credit_record:
            credit_record = CreditRecord(
                user_id=request.user_id,
                total_diagnosis=PAYMENT_CONFIG["free_diagnosis_count"],
                used_diagnosis=0,
                free_diagnosis_used=0,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.add(credit_record)
            db.commit()

        # 计算剩余次数
        remaining = credit_record.total_diagnosis - credit_record.used_diagnosis
        free_remaining = PAYMENT_CONFIG["free_diagnosis_count"] - credit_record.free_diagnosis_used

        return JSONResponse({
            "code": 0,
            "message": "查询成功",
            "data": {
                "has_credit": remaining > 0,
                "remaining_diagnosis": max(0, remaining),
                "free_diagnosis_remaining": max(0, free_remaining),
                "total_diagnosis": credit_record.total_diagnosis,
                "used_diagnosis": credit_record.used_diagnosis
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检查诊断额度失败: {str(e)}")
        raise HTTPException(status_code=500, detail="检查诊断额度失败")

@router.post("/diagnosis/consume", response_class=JSONResponse)
async def consume_diagnosis_credit(
    request: DiagnosisRequest,
    db=Depends(get_db)
):
    """
    消耗一次诊断额度
    - 优先使用免费次数
    - 记录诊断历史
    """
    try:
        # 查询用户
        user = db.query(User).filter(User.user_id == request.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 查询额度记录
        credit_record = db.query(CreditRecord).filter(
            CreditRecord.user_id == request.user_id
        ).first()

        if not credit_record:
            raise HTTPException(status_code=400, detail="用户额度记录不存在")

        # 检查是否有剩余额度
        remaining = credit_record.total_diagnosis - credit_record.used_diagnosis
        if remaining <= 0:
            raise HTTPException(status_code=403, detail="诊断次数不足，请购买")

        # 消耗额度
        credit_record.used_diagnosis += 1
        credit_record.updated_at = datetime.now()

        # 记录诊断历史
        diagnosis_record = DiagnosisRecord(
            user_id=request.user_id,
            query=request.query,
            diagnosis_count=1,
            operation_type="diagnosis",
            created_at=datetime.now()
        )
        db.add(diagnosis_record)
        db.commit()

        return JSONResponse({
            "code": 0,
            "message": "诊断额度消耗成功",
            "data": {
                "remaining_diagnosis": credit_record.total_diagnosis - credit_record.used_diagnosis,
                "total_diagnosis": credit_record.total_diagnosis,
                "used_diagnosis": credit_record.used_diagnosis
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"消耗诊断额度失败: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="消耗诊断额度失败")

@router.get("/user/credit/{user_id}", response_class=JSONResponse)
async def get_user_credit(
    user_id: str,
    db=Depends(get_db)
):
    """
    获取用户额度信息
    """
    try:
        # 查询用户
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 查询额度记录
        credit_record = db.query(CreditRecord).filter(
            CreditRecord.user_id == user_id
        ).first()

        if not credit_record:
            # 返回默认额度
            return JSONResponse({
                "code": 0,
                "message": "查询成功",
                "data": UserCreditResponse(
                    user_id=user_id,
                    total_diagnosis=PAYMENT_CONFIG["free_diagnosis_count"],
                    used_diagnosis=0,
                    remaining_diagnosis=PAYMENT_CONFIG["free_diagnosis_count"],
                    free_diagnosis_used=0,
                    is_premium=False
                ).dict()
            })

        remaining = credit_record.total_diagnosis - credit_record.used_diagnosis

        return JSONResponse({
            "code": 0,
            "message": "查询成功",
            "data": UserCreditResponse(
                user_id=user_id,
                total_diagnosis=credit_record.total_diagnosis,
                used_diagnosis=credit_record.used_diagnosis,
                remaining_diagnosis=max(0, remaining),
                free_diagnosis_used=credit_record.free_diagnosis_used,
                is_premium=credit_record.total_diagnosis > PAYMENT_CONFIG["free_diagnosis_count"]
            ).dict()
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户额度失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取用户额度失败")

@router.get("/payment/history/{user_id}", response_class=JSONResponse)
async def get_payment_history(
    user_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=50, description="每页数量"),
    db=Depends(get_db)
):
    """
    获取用户支付历史
    """
    try:
        # 查询用户
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 查询支付记录
        offset = (page - 1) * page_size
        payment_records = db.query(PaymentRecord).filter(
            PaymentRecord.user_id == user_id
        ).order_by(PaymentRecord.created_at.desc()).offset(offset).limit(page_size).all()

        # 查询总数
        total = db.query(PaymentRecord).filter(
            PaymentRecord.user_id == user_id
        ).count()

        return JSONResponse({
            "code": 0,
            "message": "查询成功",
            "data": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "records": [
                    {
                        "order_id": record.order_id,
                        "diagnosis_count": record.diagnosis_count,
                        "total_amount": str(record.total_amount),
                        "payment_method": record.payment_method,
                        "payment_status": record.payment_status,
                        "created_at": record.created_at.isoformat() if record.created_at else None
                    }
                    for record in payment_records
                ]
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取支付历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取支付历史失败")

@router.get("/diagnosis/history/{user_id}", response_class=JSONResponse)
async def get_diagnosis_history(
    user_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=50, description="每页数量"),
    db=Depends(get_db)
):
    """
    获取用户诊断历史
    """
    try:
        # 查询用户
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 查询诊断记录
        offset = (page - 1) * page_size
        diagnosis_records = db.query(DiagnosisRecord).filter(
            DiagnosisRecord.user_id == user_id
        ).order_by(DiagnosisRecord.created_at.desc()).offset(offset).limit(page_size).all()

        # 查询总数
        total = db.query(DiagnosisRecord).filter(
            DiagnosisRecord.user_id == user_id
        ).count()

        return JSONResponse({
            "code": 0,
            "message": "查询成功",
            "data": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "records": [
                    {
                        "id": record.id,
                        "query": record.query,
                        "diagnosis_count": record.diagnosis_count,
                        "operation_type": record.operation_type,
                        "created_at": record.created_at.isoformat() if record.created_at else None
                    }
                    for record in diagnosis_records
                ]
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取诊断历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取诊断历史失败")

# ============================================================
# 场景识别与路由（原有逻辑保持不变）
# ============================================================

def _detect_scenario(query: str) -> Optional[ScenarioType]:
    """
    场景识别核心逻辑
    优先级: 强信号 > 组合规则 > 关键词匹配
    """
    if not query or not query.strip():
        return None

    query_lower = query.lower().strip()

    # 1. 强信号检测
    for signal, scenario in STRONG_SIGNALS.items():
        if signal in query:
            logger.debug(f"强信号匹配: {signal} -> {scenario}")
            return scenario

    # 2. 组合规则检测
    for scenario, combos in COMBO_RULES.items():
        for combo in combos:
            if all(keyword in query for keyword in combo):
                logger.debug(f"组合规则匹配: {combo} -> {scenario}")
                return scenario

    # 3. 关键词匹配
    for scenario, keywords in SCENARIO_KEYWORDS.items():
        for keyword in keywords:
            if keyword in query:
                logger.debug(f"关键词匹配: {keyword} -> {scenario}")
                return scenario

    return None

def _extract_district(query: str) -> Optional[str]:
    """提取区域信息"""
    for district in DISTRICT_KEYWORDS:
        if district in query:
            return district
    return None

@router.post("/route", response_class=JSONResponse)
async def route_query(
    request: Request,
    query: str = Form(...),
    user_id: Optional[str] = Form(None)
):
    """
    路由查询入口
    - 场景识别
    - 额度检查（如果用户已登录）
    - 返回路由结果
    """
    try:
        # 场景识别
        scenario = _detect_scenario(query)
        district = _extract_district(query)

        # 如果用户已登录，检查额度
        if user_id:
            db = next(get_db())
            try:
                credit_record = db.query(CreditRecord).filter(
                    CreditRecord.user_id == user_id
                ).first()

                if credit_record:
                    remaining = credit_record.total_diagnosis - credit_record.used_diagnosis
                    if remaining <= 0:
                        return JSONResponse({
                            "code": 403,
                            "message": "诊断次数不足，请购买",
                            "data": {
                                "need_payment": True,
                                "price": PAYMENT_CONFIG["diagnosis_price"],
                                "redirect_url": "/payment"
                            }
                        })
            finally:
                db.close()

        # 构建路由结果
        result = RouteResult(
            scenario=scenario,
            district=district,
            confidence=0.8 if scenario else 0.0,
            query=query
        )

        return JSONResponse({
            "code": 0,
            "message": "路由成功",
            "data": result.dict()
        })

    except Exception as e:
        logger.error(f"路由查询失败: {str(e)}")
        raise HTTPException(status_code=500, detail="路由查询失败")

@router.get("/health", response_class=JSONResponse)
async def health_check():
    """健康检查接口"""
    return JSONResponse({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "2.1.0"
    })
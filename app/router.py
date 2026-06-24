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
# 支付相关数据模型
# ============================================================

class CreateOrderRequest(BaseModel):
    """创建支付订单请求"""
    user_id: str = Field(..., description="用户ID")
    amount: Decimal = Field(..., ge=0.01, description="支付金额（元）")
    description: str = Field(default="升学诊断服务", description="订单描述")

class CreateOrderResponse(BaseModel):
    """创建支付订单响应"""
    order_id: str = Field(..., description="订单号")
    prepay_id: str = Field(..., description="微信预支付ID")
    nonce_str: str = Field(..., description="随机字符串")
    sign: str = Field(..., description="签名")
    timestamp: int = Field(..., description="时间戳")

class NotifyRequest(BaseModel):
    """微信支付回调通知"""
    return_code: str = Field(..., description="返回状态码")
    return_msg: str = Field(default="", description="返回信息")
    result_code: str = Field(default="", description="业务结果")
    out_trade_no: str = Field(default="", description="商户订单号")
    transaction_id: str = Field(default="", description="微信支付订单号")
    total_fee: int = Field(default=0, description="订单金额（分）")
    time_end: str = Field(default="", description="支付完成时间")
    sign: str = Field(default="", description="签名")

class BalanceResponse(BaseModel):
    """余额查询响应"""
    user_id: str = Field(..., description="用户ID")
    total_diagnoses: int = Field(..., description="总诊断次数")
    used_diagnoses: int = Field(..., description="已使用诊断次数")
    remaining_diagnoses: int = Field(..., description="剩余诊断次数")
    free_diagnoses_used: int = Field(..., description="已使用的免费诊断次数")

class ConsumeRequest(BaseModel):
    """消耗诊断次数请求"""
    user_id: str = Field(..., description="用户ID")
    diagnosis_id: str = Field(..., description="诊断记录ID")

class ConsumeResponse(BaseModel):
    """消耗诊断次数响应"""
    success: bool = Field(..., description="是否成功")
    remaining_diagnoses: int = Field(..., description="剩余诊断次数")
    message: str = Field(default="", description="提示信息")


# ============================================================
# 支付相关辅助函数
# ============================================================

def generate_order_id() -> str:
    """生成唯一订单号"""
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d%H%M%S")
    random_part = secrets.token_hex(4).upper()
    return f"DX{timestamp}{random_part}"

def generate_nonce_str() -> str:
    """生成随机字符串"""
    return secrets.token_hex(16)

def generate_sign(params: Dict[str, Any], key: str) -> str:
    """生成微信支付签名（MD5）"""
    # 按字典序排序参数
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    # 拼接字符串
    sign_str = "&".join([f"{k}={v}" for k, v in sorted_params if v != "" and k != "sign"])
    sign_str += f"&key={key}"
    # MD5加密
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

def verify_wechat_signature(params: Dict[str, Any], key: str) -> bool:
    """验证微信回调签名"""
    sign = params.pop("sign", "")
    if not sign:
        return False
    expected_sign = generate_sign(params, key)
    return sign == expected_sign

def get_user_credit(db_session, user_id: str) -> Optional[CreditRecord]:
    """获取用户信用记录"""
    return db_session.query(CreditRecord).filter(CreditRecord.user_id == user_id).first()

def create_user_credit(db_session, user_id: str) -> CreditRecord:
    """创建用户信用记录"""
    credit = CreditRecord(
        user_id=user_id,
        total_diagnoses=PAYMENT_CONFIG["free_diagnosis_count"],
        used_diagnoses=0,
        free_diagnoses_used=0,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    db_session.add(credit)
    db_session.commit()
    return credit

def check_diagnosis_availability(db_session, user_id: str) -> Tuple[bool, str]:
    """检查用户是否有可用的诊断次数"""
    credit = get_user_credit(db_session, user_id)
    if not credit:
        # 新用户，创建信用记录并返回可用
        credit = create_user_credit(db_session, user_id)
        return True, "新用户免费诊断次数可用"
    
    if credit.remaining_diagnoses > 0:
        return True, f"剩余诊断次数: {credit.remaining_diagnoses}"
    
    return False, "诊断次数已用完，请充值"


# ============================================================
# 支付路由
# ============================================================

@router.post("/api/payment/create", response_model=CreateOrderResponse)
async def create_payment_order(
    request: CreateOrderRequest,
    db_session = Depends(get_db)
):
    """
    创建支付订单
    - 生成订单号
    - 调用微信支付统一下单API
    - 返回预支付信息
    """
    try:
        # 验证用户是否存在
        user = db_session.query(User).filter(User.user_id == request.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 生成订单号
        order_id = generate_order_id()
        
        # 计算金额（分）
        total_fee = int(request.amount * 100)
        
        # 构建微信统一下单参数
        nonce_str = generate_nonce_str()
        timestamp = int(datetime.now().timestamp())
        
        # 模拟微信支付统一下单（实际应调用微信API）
        # 这里模拟返回预支付ID
        prepay_id = f"wx{secrets.token_hex(16)}"
        
        # 构建签名参数
        sign_params = {
            "appid": settings.WX_APPID,
            "mch_id": settings.WX_MCHID,
            "nonce_str": nonce_str,
            "body": request.description,
            "out_trade_no": order_id,
            "total_fee": str(total_fee),
            "spbill_create_ip": "127.0.0.1",
            "notify_url": f"{settings.BASE_URL}/api/payment/notify",
            "trade_type": "JSAPI",
            "openid": user.openid,
            "time_start": datetime.now().strftime("%Y%m%d%H%M%S"),
            "time_expire": (datetime.now() + timedelta(minutes=PAYMENT_CONFIG["payment_expire_minutes"])).strftime("%Y%m%d%H%M%S"),
        }
        
        # 生成签名
        sign = generate_sign(sign_params, settings.WX_API_KEY)
        
        # 保存支付记录到数据库
        payment_record = PaymentRecord(
            order_id=order_id,
            user_id=request.user_id,
            amount=request.amount,
            total_fee=total_fee,
            status="pending",
            prepay_id=prepay_id,
            nonce_str=nonce_str,
            sign=sign,
            description=request.description,
            created_at=datetime.now(),
            expire_at=datetime.now() + timedelta(minutes=PAYMENT_CONFIG["payment_expire_minutes"])
        )
        db_session.add(payment_record)
        db_session.commit()
        
        logger.info(f"创建支付订单成功: order_id={order_id}, user_id={request.user_id}, amount={request.amount}")
        
        return CreateOrderResponse(
            order_id=order_id,
            prepay_id=prepay_id,
            nonce_str=nonce_str,
            sign=sign,
            timestamp=timestamp
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建支付订单失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建支付订单失败: {str(e)}")


@router.post("/api/payment/notify")
async def payment_notify(
    request: Request,
    db_session = Depends(get_db)
):
    """
    微信支付回调通知
    - 验证签名
    - 更新订单状态
    - 增加用户诊断次数
    """
    try:
        # 获取原始XML数据
        body = await request.body()
        xml_data = body.decode("utf-8")
        
        # 解析XML（简化处理，实际应使用xml.etree.ElementTree）
        # 这里模拟解析结果
        notify_data = {
            "return_code": "SUCCESS",
            "return_msg": "OK",
            "result_code": "SUCCESS",
            "out_trade_no": "",
            "transaction_id": "",
            "total_fee": "0",
            "time_end": datetime.now().strftime("%Y%m%d%H%M%S"),
            "sign": ""
        }
        
        # 实际应从XML中解析，这里简化处理
        # 假设从请求中获取JSON数据
        try:
            json_data = await request.json()
            notify_data.update(json_data)
        except:
            pass
        
        # 验证签名
        if not verify_wechat_signature(notify_data, settings.WX_API_KEY):
            logger.warning(f"微信回调签名验证失败: {notify_data}")
            return {"return_code": "FAIL", "return_msg": "签名验证失败"}
        
        # 检查支付结果
        if notify_data.get("return_code") != "SUCCESS" or notify_data.get("result_code") != "SUCCESS":
            logger.warning(f"微信回调支付失败: {notify_data}")
            return {"return_code": "FAIL", "return_msg": "支付失败"}
        
        order_id = notify_data.get("out_trade_no", "")
        transaction_id = notify_data.get("transaction_id", "")
        total_fee = int(notify_data.get("total_fee", 0))
        
        # 查询订单
        payment_record = db_session.query(PaymentRecord).filter(
            PaymentRecord.order_id == order_id
        ).first()
        
        if not payment_record:
            logger.error(f"订单不存在: {order_id}")
            return {"return_code": "FAIL", "return_msg": "订单不存在"}
        
        if payment_record.status == "paid":
            logger.info(f"订单已支付，忽略重复通知: {order_id}")
            return {"return_code": "SUCCESS", "return_msg": "OK"}
        
        # 更新订单状态
        payment_record.status = "paid"
        payment_record.transaction_id = transaction_id
        payment_record.paid_at = datetime.now()
        payment_record.updated_at = datetime.now()
        
        # 计算购买次数（1元=1次）
        buy_count = total_fee // 100  # 转换为元
        
        # 更新用户信用记录
        credit = get_user_credit(db_session, payment_record.user_id)
        if credit:
            credit.total_diagnoses += buy_count
            credit.updated_at = datetime.now()
        else:
            credit = CreditRecord(
                user_id=payment_record.user_id,
                total_diagnoses=buy_count,
                used_diagnoses=0,
                free_diagnoses_used=0,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db_session.add(credit)
        
        db_session.commit()
        
        logger.info(f"支付回调处理成功: order_id={order_id}, user_id={payment_record.user_id}, buy_count={buy_count}")
        
        return {"return_code": "SUCCESS", "return_msg": "OK"}
        
    except Exception as e:
        logger.error(f"支付回调处理失败: {str(e)}")
        return {"return_code": "FAIL", "return_msg": f"处理失败: {str(e)}"}


@router.get("/api/payment/balance", response_model=BalanceResponse)
async def get_balance(
    user_id: str = Query(..., description="用户ID"),
    db_session = Depends(get_db)
):
    """
    查询用户余额（诊断次数）
    - 返回总次数、已使用次数、剩余次数
    """
    try:
        # 验证用户是否存在
        user = db_session.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 获取用户信用记录
        credit = get_user_credit(db_session, user_id)
        if not credit:
            # 新用户，返回默认值
            return BalanceResponse(
                user_id=user_id,
                total_diagnoses=PAYMENT_CONFIG["free_diagnosis_count"],
                used_diagnoses=0,
                remaining_diagnoses=PAYMENT_CONFIG["free_diagnosis_count"],
                free_diagnoses_used=0
            )
        
        return BalanceResponse(
            user_id=user_id,
            total_diagnoses=credit.total_diagnoses,
            used_diagnoses=credit.used_diagnoses,
            remaining_diagnoses=credit.remaining_diagnoses,
            free_diagnoses_used=credit.free_diagnoses_used
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询余额失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询余额失败: {str(e)}")


@router.post("/api/payment/consume", response_model=ConsumeResponse)
async def consume_diagnosis(
    request: ConsumeRequest,
    db_session = Depends(get_db)
):
    """
    消耗一次诊断次数
    - 检查用户是否有可用次数
    - 记录诊断消耗
    - 更新用户信用记录
    """
    try:
        # 验证用户是否存在
        user = db_session.query(User).filter(User.user_id == request.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 检查诊断记录是否存在
        diagnosis = db_session.query(DiagnosisRecord).filter(
            DiagnosisRecord.diagnosis_id == request.diagnosis_id
        ).first()
        if not diagnosis:
            raise HTTPException(status_code=404, detail="诊断记录不存在")
        
        # 检查是否已经消耗过
        if diagnosis.is_paid:
            return ConsumeResponse(
                success=True,
                remaining_diagnoses=0,
                message="该诊断已消耗过次数"
            )
        
        # 检查用户是否有可用次数
        available, message = check_diagnosis_availability(db_session, request.user_id)
        if not available:
            raise HTTPException(status_code=403, detail=message)
        
        # 获取用户信用记录
        credit = get_user_credit(db_session, request.user_id)
        if not credit:
            credit = create_user_credit(db_session, request.user_id)
        
        # 更新信用记录
        credit.used_diagnoses += 1
        credit.updated_at = datetime.now()
        
        # 如果是免费次数，记录免费使用
        if credit.free_diagnoses_used < PAYMENT_CONFIG["free_diagnosis_count"]:
            credit.free_diagnoses_used += 1
        
        # 更新诊断记录
        diagnosis.is_paid = True
        diagnosis.paid_at = datetime.now()
        
        db_session.commit()
        
        logger.info(f"消耗诊断次数成功: user_id={request.user_id}, diagnosis_id={request.diagnosis_id}, remaining={credit.remaining_diagnoses}")
        
        return ConsumeResponse(
            success=True,
            remaining_diagnoses=credit.remaining_diagnoses,
            message=f"诊断次数消耗成功，剩余{credit.remaining_diagnoses}次"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"消耗诊断次数失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"消耗诊断次数失败: {str(e)}")


# ============================================================
# 原有路由（保持不变）
# ============================================================

# ... 原有路由代码保持不变 ...

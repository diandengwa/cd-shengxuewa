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
    ],
    ScenarioType.KINDERGARTEN_TO_PRIMARY: [
        "wiki/policies/2026"
    ],
    ScenarioType.TRANSFER: [
        "wiki/policies/transfer"
    ],
    ScenarioType.MIDDLE_SCHOOL_EXAM: [
        "wiki/policies/2026"
    ],
}

# ============================================================
# 辅助函数
# ============================================================

def generate_order_id(user_id: int) -> str:
    """生成唯一订单ID"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = secrets.token_hex(4)
    return f"ORD{timestamp}{user_id:06d}{random_str}"

def check_user_credit(user_id: int, db) -> Tuple[bool, int]:
    """检查用户剩余诊断次数"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False, 0
    
    # 计算已使用的诊断次数
    used_count = db.query(DiagnosisRecord).filter(
        DiagnosisRecord.user_id == user_id,
        DiagnosisRecord.created_at >= datetime.now() - timedelta(days=30)
    ).count()
    
    # 计算可用次数（免费次数 + 购买次数）
    total_credits = user.free_diagnosis_count + user.purchased_diagnosis_count
    remaining = total_credits - used_count
    
    return remaining > 0, max(0, remaining)

def deduct_credit(user_id: int, db) -> bool:
    """扣除一次诊断次数"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    
    # 优先使用免费次数
    if user.free_diagnosis_count > 0:
        user.free_diagnosis_count -= 1
    elif user.purchased_diagnosis_count > 0:
        user.purchased_diagnosis_count -= 1
    else:
        return False
    
    db.commit()
    return True

# ============================================================
# 支付相关路由
# ============================================================

class PaymentCreateRequest(BaseModel):
    """创建支付订单请求"""
    user_id: int = Field(..., description="用户ID")
    amount: Decimal = Field(default=Decimal("1.00"), description="支付金额")
    payment_method: str = Field(default="wechat", description="支付方式")

class PaymentCreateResponse(BaseModel):
    """创建支付订单响应"""
    order_id: str
    amount: Decimal
    status: str
    qr_code_url: Optional[str] = None
    expire_time: datetime

class PaymentCallbackRequest(BaseModel):
    """支付回调请求"""
    order_id: str
    transaction_id: str
    status: str
    amount: Decimal
    sign: str

@router.post("/payment/create", response_model=PaymentCreateResponse)
async def create_payment_order(
    request: PaymentCreateRequest,
    db: Session = Depends(get_db)
):
    """
    创建支付订单
    - 生成唯一订单号
    - 记录支付记录
    - 返回支付二维码
    """
    try:
        # 验证用户存在
        user = db.query(User).filter(User.id == request.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 生成订单ID
        order_id = generate_order_id(request.user_id)
        
        # 计算过期时间
        expire_time = datetime.now() + timedelta(minutes=PAYMENT_CONFIG["payment_expire_minutes"])
        
        # 创建支付记录
        payment_record = PaymentRecord(
            order_id=order_id,
            user_id=request.user_id,
            amount=request.amount,
            payment_method=request.payment_method,
            status="pending",
            expire_time=expire_time,
            created_at=datetime.now()
        )
        db.add(payment_record)
        db.commit()
        
        # 生成支付二维码（模拟）
        qr_code_url = f"https://api.example.com/qrcode/{order_id}"
        
        return PaymentCreateResponse(
            order_id=order_id,
            amount=request.amount,
            status="pending",
            qr_code_url=qr_code_url,
            expire_time=expire_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建支付订单失败: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="创建支付订单失败")

@router.post("/payment/callback")
async def payment_callback(
    request: PaymentCallbackRequest,
    db: Session = Depends(get_db)
):
    """
    支付回调处理
    - 验证签名
    - 更新支付状态
    - 增加用户诊断次数
    """
    try:
        # 验证签名（模拟）
        expected_sign = hashlib.md5(
            f"{request.order_id}{request.transaction_id}{request.amount}".encode()
        ).hexdigest()
        
        if request.sign != expected_sign:
            raise HTTPException(status_code=400, detail="签名验证失败")
        
        # 查找支付记录
        payment_record = db.query(PaymentRecord).filter(
            PaymentRecord.order_id == request.order_id
        ).first()
        
        if not payment_record:
            raise HTTPException(status_code=404, detail="支付记录不存在")
        
        if payment_record.status == "completed":
            return {"status": "success", "message": "订单已处理"}
        
        # 更新支付状态
        payment_record.status = request.status
        payment_record.transaction_id = request.transaction_id
        payment_record.paid_at = datetime.now()
        
        # 如果支付成功，增加用户诊断次数
        if request.status == "completed":
            user = db.query(User).filter(User.id == payment_record.user_id).first()
            if user:
                # 每1元增加1次诊断
                diagnosis_count = int(payment_record.amount)
                user.purchased_diagnosis_count += diagnosis_count
                
                # 记录信用变更
                credit_record = CreditRecord(
                    user_id=user.id,
                    amount=diagnosis_count,
                    type="purchase",
                    description=f"购买{diagnosis_count}次诊断服务",
                    created_at=datetime.now()
                )
                db.add(credit_record)
        
        db.commit()
        
        return {"status": "success", "message": "回调处理完成"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"支付回调处理失败: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="支付回调处理失败")

@router.get("/payment/status/{order_id}")
async def get_payment_status(
    order_id: str,
    db: Session = Depends(get_db)
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
        
        return {
            "order_id": payment_record.order_id,
            "status": payment_record.status,
            "amount": payment_record.amount,
            "created_at": payment_record.created_at,
            "paid_at": payment_record.paid_at,
            "expire_time": payment_record.expire_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询支付状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail="查询支付状态失败")

# ============================================================
# 诊断相关路由
# ============================================================

class DiagnosisRequest(BaseModel):
    """诊断请求"""
    user_id: int = Field(..., description="用户ID")
    query: str = Field(..., description="用户查询内容")
    scenario: Optional[str] = Field(None, description="场景类型")

class DiagnosisResponse(BaseModel):
    """诊断响应"""
    diagnosis_id: int
    scenario: str
    result: Dict[str, Any]
    remaining_credits: int
    is_free: bool

@router.post("/diagnosis", response_model=DiagnosisResponse)
async def perform_diagnosis(
    request: DiagnosisRequest,
    db: Session = Depends(get_db)
):
    """
    执行诊断
    - 检查用户剩余次数
    - 执行场景识别
    - 返回诊断结果
    """
    try:
        # 检查用户信用
        has_credit, remaining = check_user_credit(request.user_id, db)
        if not has_credit:
            raise HTTPException(
                status_code=402,
                detail="诊断次数不足，请购买诊断服务",
                headers={"X-Remaining-Credits": str(remaining)}
            )
        
        # 执行场景识别
        scenario = identify_scenario(request.query)
        
        # 执行诊断逻辑
        diagnosis_result = await execute_diagnosis(request.query, scenario, db)
        
        # 扣除诊断次数
        if not deduct_credit(request.user_id, db):
            raise HTTPException(status_code=500, detail="扣除诊断次数失败")
        
        # 记录诊断记录
        diagnosis_record = DiagnosisRecord(
            user_id=request.user_id,
            scenario=scenario.value if scenario else "unknown",
            query=request.query,
            result=json.dumps(diagnosis_result, ensure_ascii=False),
            created_at=datetime.now()
        )
        db.add(diagnosis_record)
        db.commit()
        
        # 获取更新后的剩余次数
        _, remaining = check_user_credit(request.user_id, db)
        
        return DiagnosisResponse(
            diagnosis_id=diagnosis_record.id,
            scenario=scenario.value if scenario else "unknown",
            result=diagnosis_result,
            remaining_credits=remaining,
            is_free=False
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行诊断失败: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="执行诊断失败")

@router.get("/diagnosis/history/{user_id}")
async def get_diagnosis_history(
    user_id: int,
    limit: int = Query(default=10, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """
    获取诊断历史
    """
    try:
        records = db.query(DiagnosisRecord).filter(
            DiagnosisRecord.user_id == user_id
        ).order_by(
            DiagnosisRecord.created_at.desc()
        ).offset(offset).limit(limit).all()
        
        return [
            {
                "id": record.id,
                "scenario": record.scenario,
                "query": record.query[:100],  # 截取前100字符
                "result": json.loads(record.result) if record.result else {},
                "created_at": record.created_at
            }
            for record in records
        ]
        
    except Exception as e:
        logger.error(f"获取诊断历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取诊断历史失败")

# ============================================================
# 用户信用管理路由
# ============================================================

@router.get("/user/credits/{user_id}")
async def get_user_credits(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    获取用户诊断次数信息
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        has_credit, remaining = check_user_credit(user_id, db)
        
        return {
            "user_id": user_id,
            "free_diagnosis_count": user.free_diagnosis_count,
            "purchased_diagnosis_count": user.purchased_diagnosis_count,
            "remaining_credits": remaining,
            "has_credit": has_credit,
            "diagnosis_price": PAYMENT_CONFIG["diagnosis_price"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户信用失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取用户信用失败")

@router.post("/user/credits/add")
async def add_user_credits(
    user_id: int = Form(...),
    amount: int = Form(..., ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    管理员添加用户诊断次数
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        user.purchased_diagnosis_count += amount
        
        credit_record = CreditRecord(
            user_id=user_id,
            amount=amount,
            type="admin_add",
            description=f"管理员添加{amount}次诊断次数",
            created_at=datetime.now()
        )
        db.add(credit_record)
        db.commit()
        
        return {
            "status": "success",
            "user_id": user_id,
            "added_amount": amount,
            "total_purchased": user.purchased_diagnosis_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加用户信用失败: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="添加用户信用失败")

# ============================================================
# 场景识别函数
# ============================================================

def identify_scenario(query: str) -> Optional[ScenarioType]:
    """
    识别用户查询的场景类型
    """
    if not query:
        return None
    
    # 强信号匹配
    for signal, scenario in STRONG_SIGNALS.items():
        if signal in query:
            return scenario
    
    # 关键词匹配
    for scenario, keywords in SCENARIO_KEYWORDS.items():
        for keyword in keywords:
            if keyword in query:
                return scenario
    
    # 组合规则匹配
    for scenario, rules in COMBO_RULES.items():
        for rule in rules:
            if all(keyword in query for keyword in rule):
                return scenario
    
    return None

async def execute_diagnosis(query: str, scenario: Optional[ScenarioType], db: Session) -> Dict[str, Any]:
    """
    执行诊断逻辑
    """
    result = {
        "query": query,
        "scenario": scenario.value if scenario else "unknown",
        "analysis": {},
        "recommendations": []
    }
    
    if scenario == ScenarioType.KINDERGARTEN_TO_PRIMARY:
        result["analysis"] = {
            "type": "幼升小",
            "key_points": ["入学年龄", "户籍要求", "划片范围", "报名时间"],
            "district_info": extract_district_info(query)
        }
        result["recommendations"] = [
            "查看目标小学的划片范围",
            "确认入学年龄要求",
            "准备相关报名材料"
        ]
        
    elif scenario == ScenarioType.PRIMARY_TO_MIDDLE:
        result["analysis"] = {
            "type": "小升初",
            "key_points": ["对口初中", "大摇号", "民办摇号", "指标到校"],
            "district_info": extract_district_info(query)
        }
        result["recommendations"] = [
            "查询对口初中信息",
            "了解大摇号政策",
            "准备升学材料"
        ]
        
    elif scenario == ScenarioType.TRANSFER:
        result["analysis"] = {
            "type": "随迁入学",
            "key_points": ["居住证", "社保要求", "积分政策", "材料清单"],
            "district_info": extract_district_info(query)
        }
        result["recommendations"] = [
            "确认居住证是否有效",
            "检查社保缴纳情况",
            "准备随迁入学材料"
        ]
        
    elif scenario == ScenarioType.MIDDLE_SCHOOL_EXAM:
        result["analysis"] = {
            "type": "中考",
            "key_points": ["录取分数线", "志愿填报", "指标到校", "普高线"],
            "district_info": extract_district_info(query)
        }
        result["recommendations"] = [
            "查询历年录取分数线",
            "了解志愿填报规则",
            "关注指标到校政策"
        ]
        
    else:
        result["analysis"] = {
            "type": "通用咨询",
            "key_points": ["政策咨询", "升学规划"],
            "district_info": extract_district_info(query)
        }
        result["recommendations"] = [
            "查看相关政策页面",
            "咨询升学规划师"
        ]
    
    return result

def extract_district_info(query: str) -> Dict[str, Any]:
    """
    提取查询中的区域信息
    """
    districts_found = []
    for district in DISTRICT_KEYWORDS:
        if district in query:
            districts_found.append(district)
    
    return {
        "districts": districts_found,
        "has_district": len(districts_found) > 0
    }

# ============================================================
# 健康检查
# ============================================================

@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.1.0"
    }
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
        "wiki/policies/2026_成都市_义务教育招生入学通知.md",
        "wiki/policies/2026_成都市_义务教育招生入学政策解读.md",
        "wiki/policies/2025_成都市_义务教育招生入学通知.md",
        "wiki/policies/2026_成都市_6月1日起报名！民办小一报名操作手册来啦.md",
        "wiki/policies/2026_高新区_中和AB片区小一招生录取公告.md",
        "wiki/policies/2026_高新区_中和AB片区小一招生录取8个问答.md",
    ],
    ScenarioType.KINDERGARTEN_TO_PRIMARY: [
        "wiki/policies/2026_成都市_义务教育招生入学通知.md",
        "wiki/policies/2026_成都市_义务教育招生入学政策解读.md",
        "wiki/policies/2026_成都市_幼儿园招生入园通知.md",
    ],
}


# ============================================================
# 以下为原有路由函数（保持不变）
# ============================================================

@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/")
async def index(request: Request):
    """首页"""
    return HTMLResponse(content=open("templates/index.html", encoding="utf-8").read())


@router.post("/api/diagnose")
async def diagnose(
    request: Request,
    question: str = Form(...),
    db=Depends(get_db)
):
    """
    诊断接口：分析用户问题，返回诊断结果
    """
    try:
        # 这里保留原有的诊断逻辑
        # 识别场景类型
        scenario = _identify_scenario(question)
        
        # 获取相关政策
        policies = _get_relevant_policies(scenario, question)
        
        # 返回诊断结果
        return JSONResponse({
            "scenario": scenario.value if scenario else "unknown",
            "policies": policies,
            "suggestions": _generate_suggestions(scenario, question)
        })
    except Exception as e:
        logger.error(f"诊断失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="诊断服务异常")


def _identify_scenario(question: str) -> Optional[ScenarioType]:
    """
    识别用户问题的场景类型
    """
    if not question:
        return None
    
    # 强信号匹配
    for keyword, scenario in STRONG_SIGNALS.items():
        if keyword in question:
            return scenario
    
    # 组合规则匹配
    for scenario, rules in COMBO_RULES.items():
        for rule in rules:
            if all(kw in question for kw in rule):
                return scenario
    
    # 关键词匹配
    for scenario, keywords in SCENARIO_KEYWORDS.items():
        for keyword in keywords:
            if keyword in question:
                return scenario
    
    return None


def _get_relevant_policies(scenario: Optional[ScenarioType], question: str) -> List[str]:
    """
    获取相关政策文档
    """
    if not scenario:
        return []
    
    # 从核心政策页面获取
    policy_pages = CORE_POLICY_PAGES.get(scenario, [])
    
    # 从wiki加载器获取更多政策
    try:
        wiki_policies = wiki_loader.search_policies(question, scenario)
        policy_pages.extend(wiki_policies)
    except Exception as e:
        logger.warning(f"从wiki加载政策失败: {str(e)}")
    
    return list(set(policy_pages))[:5]  # 去重并限制数量


def _generate_suggestions(scenario: Optional[ScenarioType], question: str) -> List[str]:
    """
    生成诊断建议
    """
    suggestions = []
    
    if not scenario:
        suggestions.append("请提供更详细的升学问题描述，例如：'2026年小升初政策'")
        return suggestions
    
    # 根据场景生成建议
    scenario_suggestions = {
        ScenarioType.KINDERGARTEN_TO_PRIMARY: [
            "建议关注各区教育局发布的划片范围公告",
            "民办小学报名通常在6月初开始，请提前准备材料",
            "户籍与房产一致是入学的重要条件"
        ],
        ScenarioType.PRIMARY_TO_MIDDLE: [
            "小升初主要依据划片入学，请确认所在片区",
            "大摇号报名通常在7月初进行",
            "民办初中招生简章一般在5月发布"
        ],
        ScenarioType.TRANSFER: [
            "随迁子女入学需要提供居住证和社保证明",
            "建议提前6个月准备相关材料",
            "各区对社保缴纳年限要求可能不同"
        ],
        ScenarioType.MIDDLE_SCHOOL_EXAM: [
            "中考报名通常在3月进行",
            "志愿填报是升学关键环节，建议参考往年录取分数线",
            "指标到校政策对部分学生有利"
        ]
    }
    
    suggestions = scenario_suggestions.get(scenario, ["请咨询当地教育部门获取最新政策"])
    
    return suggestions


@router.post("/api/payment/create")
async def create_payment(
    request: Request,
    user_id: str = Form(...),
    amount: Decimal = Form(default=PAYMENT_CONFIG["diagnosis_price"]),
    db=Depends(get_db)
):
    """
    创建支付订单
    """
    try:
        # 生成订单号
        order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4)}"
        
        # 创建支付记录
        payment = PaymentRecord(
            user_id=user_id,
            order_id=order_id,
            amount=amount,
            status="pending",
            created_at=datetime.now(),
            expire_at=datetime.now() + timedelta(minutes=PAYMENT_CONFIG["payment_expire_minutes"])
        )
        
        db.add(payment)
        db.commit()
        
        return JSONResponse({
            "order_id": order_id,
            "amount": str(amount),
            "expire_at": payment.expire_at.isoformat(),
            "payment_url": f"/api/payment/pay/{order_id}"
        })
    except Exception as e:
        logger.error(f"创建支付订单失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="创建支付订单失败")


@router.get("/api/payment/status/{order_id}")
async def get_payment_status(
    order_id: str,
    db=Depends(get_db)
):
    """
    查询支付状态
    """
    try:
        payment = db.query(PaymentRecord).filter(PaymentRecord.order_id == order_id).first()
        if not payment:
            raise HTTPException(status_code=404, detail="订单不存在")
        
        return JSONResponse({
            "order_id": order_id,
            "status": payment.status,
            "amount": str(payment.amount),
            "created_at": payment.created_at.isoformat() if payment.created_at else None,
            "paid_at": payment.paid_at.isoformat() if payment.paid_at else None
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询支付状态失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询支付状态失败")


@router.get("/api/user/credits/{user_id}")
async def get_user_credits(
    user_id: str,
    db=Depends(get_db)
):
    """
    获取用户剩余诊断次数
    """
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            # 新用户，返回免费次数
            return JSONResponse({
                "user_id": user_id,
                "remaining_diagnoses": PAYMENT_CONFIG["free_diagnosis_count"],
                "total_diagnoses": PAYMENT_CONFIG["free_diagnosis_count"],
                "is_new_user": True
            })
        
        # 计算剩余次数
        total_purchased = db.query(CreditRecord).filter(
            CreditRecord.user_id == user_id,
            CreditRecord.credit_type == "diagnosis"
        ).count()
        
        total_used = db.query(DiagnosisRecord).filter(
            DiagnosisRecord.user_id == user_id
        ).count()
        
        remaining = PAYMENT_CONFIG["free_diagnosis_count"] + total_purchased - total_used
        
        return JSONResponse({
            "user_id": user_id,
            "remaining_diagnoses": max(0, remaining),
            "total_diagnoses": PAYMENT_CONFIG["free_diagnosis_count"] + total_purchased,
            "is_new_user": False
        })
    except Exception as e:
        logger.error(f"查询用户剩余次数失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询用户剩余次数失败")
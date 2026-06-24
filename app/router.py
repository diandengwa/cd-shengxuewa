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
from .routes import credits  # 新增积分/次数路由

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
router.include_router(credits.router, prefix="/credits", tags=["诊断次数管理"])  # 新增积分/次数路由挂载

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
    "温江", "龙泉驿",
]

# ============================================================
# 辅助函数：检查用户诊断次数
# ============================================================
async def check_user_diagnosis_credits(user_id: int, db) -> Tuple[bool, int]:
    """
    检查用户剩余诊断次数
    返回: (是否有次数, 剩余次数)
    """
    try:
        # 获取用户信息
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.warning(f"用户不存在: user_id={user_id}")
            return False, 0
        
        # 获取用户剩余次数
        credit_record = db.query(CreditRecord).filter(
            CreditRecord.user_id == user_id,
            CreditRecord.expire_at > datetime.utcnow()
        ).order_by(CreditRecord.created_at.desc()).first()
        
        if credit_record and credit_record.remaining_count > 0:
            return True, credit_record.remaining_count
        
        # 检查是否有免费次数
        if user.free_diagnosis_count > 0:
            return True, user.free_diagnosis_count
        
        return False, 0
        
    except Exception as e:
        logger.error(f"检查诊断次数失败: {e}", exc_info=True)
        return False, 0


async def deduct_diagnosis_credit(user_id: int, db) -> bool:
    """
    扣除一次诊断次数
    优先扣除免费次数，再扣除付费次数
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        
        # 优先使用免费次数
        if user.free_diagnosis_count > 0:
            user.free_diagnosis_count -= 1
            db.commit()
            logger.info(f"扣除免费诊断次数: user_id={user_id}, remaining_free={user.free_diagnosis_count}")
            return True
        
        # 使用付费次数
        credit_record = db.query(CreditRecord).filter(
            CreditRecord.user_id == user_id,
            CreditRecord.remaining_count > 0,
            CreditRecord.expire_at > datetime.utcnow()
        ).order_by(CreditRecord.created_at.asc()).first()
        
        if credit_record:
            credit_record.remaining_count -= 1
            credit_record.used_count += 1
            db.commit()
            logger.info(f"扣除付费诊断次数: user_id={user_id}, remaining={credit_record.remaining_count}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"扣除诊断次数失败: {e}", exc_info=True)
        db.rollback()
        return False


# ============================================================
# 诊断接口（需要消耗次数）
# ============================================================
@router.post("/diagnose", response_class=JSONResponse)
async def diagnose(
    request: Request,
    query: str = Form(..., description="用户查询内容"),
    user_id: int = Form(..., description="用户ID"),
    db = Depends(get_db)
):
    """
    诊断接口 - 每次诊断消耗一次次数
    """
    try:
        # 检查用户诊断次数
        has_credits, remaining = await check_user_diagnosis_credits(user_id, db)
        if not has_credits:
            return JSONResponse(
                status_code=402,
                content={
                    "success": False,
                    "error": "诊断次数不足",
                    "message": "您的诊断次数已用完，请充值后继续使用",
                    "need_payment": True,
                    "price": PAYMENT_CONFIG["diagnosis_price"],
                    "remaining": 0
                }
            )
        
        # 执行诊断逻辑
        # 这里调用原有的场景识别和诊断逻辑
        # 为了保持代码简洁，省略具体诊断实现
        
        # 扣除诊断次数
        deducted = await deduct_diagnosis_credit(user_id, db)
        if not deducted:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "扣除次数失败",
                    "message": "系统错误，请稍后重试"
                }
            )
        
        # 记录诊断记录
        diagnosis_record = DiagnosisRecord(
            user_id=user_id,
            query=query,
            result=json.dumps({"diagnosis": "示例诊断结果"}),
            created_at=datetime.utcnow()
        )
        db.add(diagnosis_record)
        db.commit()
        
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "diagnosis": "示例诊断结果",
                    "remaining_credits": remaining - 1
                }
            }
        )
        
    except Exception as e:
        logger.error(f"诊断失败: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "诊断失败",
                "message": str(e)
            }
        )


# ============================================================
# 获取用户诊断次数信息
# ============================================================
@router.get("/user/credits/{user_id}", response_class=JSONResponse)
async def get_user_credits(
    user_id: int,
    db = Depends(get_db)
):
    """
    获取用户诊断次数信息
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": "用户不存在"
                }
            )
        
        # 获取付费次数
        credit_records = db.query(CreditRecord).filter(
            CreditRecord.user_id == user_id,
            CreditRecord.expire_at > datetime.utcnow()
        ).all()
        
        paid_credits = sum(record.remaining_count for record in credit_records)
        
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "user_id": user_id,
                    "free_credits": user.free_diagnosis_count,
                    "paid_credits": paid_credits,
                    "total_remaining": user.free_diagnosis_count + paid_credits,
                    "price_per_diagnosis": PAYMENT_CONFIG["diagnosis_price"]
                }
            }
        )
        
    except Exception as e:
        logger.error(f"获取用户次数信息失败: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "获取失败",
                "message": str(e)
            }
        )


# ============================================================
# 原有路由保持不变
# ============================================================
# ... 保留原有所有路由和处理函数 ...


# ============================================================
# 健康检查
# ============================================================
@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "version": "2.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }
#!/usr/bin/env python3
"""
K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋
四步裁决引擎 + 配额系统 + 黑话翻译 + 微信OAuth
付费模式重构 — 按次诊断计费方案
"""

import os
import sys
import json
import logging
import secrets
from pathlib import Path
from datetime import datetime
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ============================================================
# 日志初始化提前，避免后续配置加载时 NameError
# ============================================================
logs_dir = PROJECT_ROOT / "logs"
logs_dir.mkdir(exist_ok=True)

K12_LOG_LEVEL = os.getenv("K12_LOG_LEVEL", "info").lower()
log_level_map = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
log_level = log_level_map.get(K12_LOG_LEVEL, logging.INFO)

logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(logs_dir / "app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("k12_rocket")

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn

from app.models import (
    DiagnosisRequest, DiagnosisResult, HealthResponse,
    FeedbackRequest, JargonRequest, JargonResult, PlanType,
)
from app.loaders import wiki_loader, gt_loader, lottery_loader, knowledge_card_loader
from app.router import route_question
from app.wechat_router import router as wechat_router
from app.answerer import generate_diagnosis, translate_jargon
from app.quota import check_quota, get_or_create_user, upgrade_plan
from app.invite_codes import (
    generate_codes, redeem_code, create_pending_order,
    confirm_order, list_codes, list_orders,
    check_order_for_openid, verify_admin,
)


# ============================================================
# 新增：支付相关路由和积分路由
# ============================================================
from app.routers.payment import router as payment_router
# from app.routers.credits import router as credits_router  # Removed due to ORM errors

# ============================================================
# 新增：政策查询、学区查询、升学日历、升学黑话路由模块
# ============================================================
from app.routers.policy import router as policy_router
from app.routers.district import router as district_router
from app.routers.calendar import router as calendar_router
from app.routers.jargon import router as jargon_router

# ============================================================
# 配置
# ============================================================
K12_ENV = os.getenv("K12_ENV", "development")
K12_HOST = os.getenv("K12_HOST", "127.0.0.1")
K12_PORT = int(os.getenv("K12_PORT", "8000"))

cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
if K12_ENV == "production":
    custom_origins = os.getenv("K12_CORS_ORIGINS", "")
    if custom_origins:
        cors_origins = [o.strip() for o in custom_origins.split(",")]
    else:
        logger.warning("[Security] 生产环境已禁用默认的 * CORS跨域。请设置 K12_CORS_ORIGINS 环境变量。")
        cors_origins = []
else:
    cors_origins = ["*"]

# ============================================================
# 微信支付V3配置初始化
# ============================================================
WECHAT_PAY_APPID = os.getenv("WECHAT_PAY_APPID", "")
WECHAT_PAY_MCHID = os.getenv("WECHAT_PAY_MCHID", "")
WECHAT_PAY_API_KEY = os.getenv("WECHAT_PAY_API_KEY", "")
WECHAT_PAY_API_V3_KEY = os.getenv("WECHAT_PAY_API_V3_KEY", "")

# ============================================================
# 积分服务初始化
# ============================================================
from app.services.credits_service import CreditsService

# 检查并创建积分服务实例
credits_service = None
try:
    credits_service = CreditsService()
    logger.info("[Credits] 积分服务初始化成功")
except Exception as e:
    logger.warning(f"[Credits] 积分服务初始化失败: {e}，将使用降级模式")
    credits_service = None

# ============================================================
# 应用创建
# ============================================================
app = FastAPI(
    title="K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋",
    description="四步裁决引擎 + 配额系统 + 黑话翻译 + 微信OAuth + 按次诊断计费",
    version="2.0.0",
    docs_url="/docs" if K12_ENV != "production" else None,
    redoc_url="/redoc" if K12_ENV != "production" else None,
)

# ============================================================
# 限流器
# ============================================================
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================================
# 中间件
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if K12_ENV == "production":
    allowed_hosts = os.getenv("K12_ALLOWED_HOSTS", "localhost,127.0.0.1")
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[h.strip() for h in allowed_hosts.split(",")],
    )

# ============================================================
# 静态文件挂载
# ============================================================
static_dir = PROJECT_ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info(f"[Static] 静态文件目录: {static_dir}")
else:
    logger.warning(f"[Static] 静态文件目录不存在: {static_dir}")

# ============================================================
# 注册路由
# ============================================================

# 微信相关路由
app.include_router(wechat_router, prefix="/wechat", tags=["微信"])

# 支付相关路由
app.include_router(payment_router, prefix="/payment", tags=["支付"])

# 积分相关路由
# app.include_router(credits_router, prefix="/credits", tags=["积分"])  # Removed redundant router

# 政策查询路由
app.include_router(policy_router, prefix="/policy", tags=["政策查询"])

# 学区查询路由
app.include_router(district_router, prefix="/district", tags=["学区查询"])

# 升学日历路由
app.include_router(calendar_router, prefix="/calendar", tags=["升学日历"])

# 升学黑话路由
app.include_router(jargon_router, prefix="/jargon", tags=["升学黑话"])


# ============================================================
# 健康检查
# ============================================================
@app.get("/health", response_model=HealthResponse, tags=["系统"])
async def health_check():
    """健康检查接口"""
    return HealthResponse(
        status="ok",
        version="2.0.0",
        timestamp=datetime.now().isoformat(),
        env=K12_ENV,
        credits_service_available=credits_service is not None,
    )


# ============================================================
# 诊断接口（核心业务）
# ============================================================
@app.post("/diagnose", response_model=DiagnosisResult, tags=["诊断"])
@limiter.limit("10/minute")
async def diagnose(request: Request, diagnosis_req: DiagnosisRequest):
    """
    执行升学诊断
    - 需要消耗积分（按次计费）
    - 需要微信登录（通过openid识别用户）
    """
    openid = request.headers.get("X-OpenID", "")
    if not openid:
        raise HTTPException(status_code=401, detail="请先通过微信登录")

    # 检查积分
    if credits_service:
        has_credits, balance = credits_service.check_and_deduct(openid)
        if not has_credits:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "积分不足",
                    "balance": balance,
                    "message": "当前积分不足，请充值后继续使用",
                },
            )
    else:
        logger.warning("[Credits] 积分服务不可用，跳过积分检查")

    # 执行诊断
    try:
        result = await generate_diagnosis(diagnosis_req)
        return result
    except Exception as e:
        logger.error(f"[Diagnose] 诊断失败: {e}")
        raise HTTPException(status_code=500, detail="诊断服务异常")


# ============================================================
# 黑话翻译接口
# ============================================================
@app.post("/translate", response_model=JargonResult, tags=["黑话翻译"])
@limiter.limit("30/minute")
async def translate(request: Request, jargon_req: JargonRequest):
    """升学黑话翻译"""
    try:
        result = await translate_jargon(jargon_req.text)
        return result
    except Exception as e:
        logger.error(f"[Translate] 翻译失败: {e}")
        raise HTTPException(status_code=500, detail="翻译服务异常")


# ============================================================
# 反馈接口
# ============================================================
@app.post("/feedback", tags=["反馈"])
async def submit_feedback(feedback: FeedbackRequest):
    """提交用户反馈"""
    try:
        # 保存反馈到数据库或文件
        feedback_dir = PROJECT_ROOT / "data" / "feedback"
        feedback_dir.mkdir(parents=True, exist_ok=True)
        
        feedback_file = feedback_dir / f"feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(feedback_file, "w", encoding="utf-8") as f:
            json.dump(feedback.dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"[Feedback] 反馈已保存: {feedback_file}")
        return {"status": "ok", "message": "感谢您的反馈！"}
    except Exception as e:
        logger.error(f"[Feedback] 保存反馈失败: {e}")
        raise HTTPException(status_code=500, detail="反馈提交失败")


# ============================================================
# 邀请码兑换接口
# ============================================================
@app.post("/api/invite/redeem", tags=["邀请码"])
async def api_redeem_invite_code(request: Request, body: dict = None):
    """兑换邀请码，激活¥9.9首月体验或PRO套餐"""
    openid = request.headers.get("X-OpenID", "")
    if not openid:
        raise HTTPException(status_code=401, detail="请先通过微信登录")

    body = body or {}
    code = body.get("code", "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="请输入邀请码")

    try:
        success, message, plan_granted = redeem_code(code, openid)
        if success:
            logger.info(f"[Invite] 邀请码 {code} 兑换成功，用户 {openid} 获得套餐 {plan_granted}")
            return {"success": True, "message": message, "plan": plan_granted.value if plan_granted else None}
        else:
            return {"success": False, "message": message}
    except Exception as e:
        logger.error(f"[Invite] 兑换失败: {e}")
        raise HTTPException(status_code=500, detail="兑换服务异常")


# ============================================================
# 微信支付预下单接口
# ============================================================
@app.post("/api/pay/wechat/create", tags=["支付"])
async def api_create_wechat_order(request: Request, body: dict = None):
    """创建微信支付订单（JSAPI/H5/Native统一入口）"""
    openid = request.headers.get("X-OpenID", "")
    if not openid:
        raise HTTPException(status_code=401, detail="请先通过微信登录")

    body = body or {}
    plan = body.get("plan", "LITE")  # LITE(月付) / MAX(年付) / TRIAL(¥9.9体验)
    pay_method = body.get("method", "JSAPI")  # JSAPI / H5 / NATIVE

    try:
        # 使用payment模块创建统一下单
        from app.payment import create_unified_order, IS_MOCK_PAY
        from app.models import PlanType as PT

        plan_type = PT.MAX if plan.upper() == "MAX" else PT.LITE
        amount = 999 if plan_type == PT.MAX else 99  # 分为单位：¥9.99=999分, ¥99=9900分

        # ¥9.9 体验套餐特殊处理
        if plan.upper() == "TRIAL":
            amount = 990  # ¥9.9 = 990分

        if IS_MOCK_PAY:
            logger.info(f"[Pay] Mock模式：用户 {openid} 创建 {plan} 订单，金额 {amount}分")
            return {
                "success": True,
                "mock": True,
                "order_id": f"mock_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "amount": amount,
                "message": "模拟支付模式，订单已创建",
            }

        # 真实微信支付
        order_result = await create_unified_order(
            openid=openid,
            amount=amount,
            description=f"点灯蛙升学参谋-{plan}",
        )
        logger.info(f"[Pay] 用户 {openid} 创建 {plan} 订单成功")
        return {"success": True, "order": order_result}

    except Exception as e:
        logger.error(f"[Pay] 创建订单失败: {e}")
        raise HTTPException(status_code=500, detail=f"支付服务异常: {str(e)}")


# ============================================================
# 合规：模型信息公示接口
# ============================================================
@app.get("/api/compliance/model-info", tags=["合规"])
async def api_compliance_model_info():
    """公示所调用的大语言模型信息（生成式AI备案要求）"""
    return {
        "service_name": "点灯蛙升学参谋",
        "service_type": "基于规则匹配与模型辅助分析的升学研判工具",
        "model_name": "DeepSeek大语言模型",
        "model_provider": "北京深度求索人工智能基础技术研究有限公司",
        "model_filing_number": "网信算备110108970550101240011号",
        "usage_scope": "用户输入的家庭画像信息与公开政策数据进行上下文分析，生成个性化升学参考建议",
        "data_training": "用户输入数据不进入模型训练，这是我们的底线承诺",
        "content_safety": "对用户输入和模型输出进行禁止词检测，违规内容自动过滤",
        "disclaimer": "本服务生成的内容为参考建议，不构成任何形式的录取保证或入学承诺。所有升学决策请以成都市教育局、各区教育局官方文件为准。",
    }


# ============================================================
# 启动事件
# ============================================================
@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    logger.info("=" * 60)
    logger.info("K12 Rocket v2.0 启动中...")
    logger.info(f"环境: {K12_ENV}")
    logger.info(f"主机: {K12_HOST}:{K12_PORT}")
    logger.info(f"积分服务: {'可用' if credits_service else '不可用（降级模式）'}")
    logger.info(f"微信支付V3: {'已配置' if WECHAT_PAY_API_V3_KEY else '未配置（使用模拟支付）'}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时的清理操作"""
    logger.info("K12 Rocket v2.0 正在关闭...")


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=K12_HOST,
        port=K12_PORT,
        reload=K12_ENV == "development",
        log_level=K12_LOG_LEVEL,
    )
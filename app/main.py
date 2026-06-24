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
from app.payment import wechat_prepay_order, handle_payment_success, decrypt_wechat_resource, IS_MOCK_PAY

# ============================================================
# 新增：支付相关路由和积分路由
# ============================================================
from app.payment_routes import router as payment_router
from app.credits_routes import router as credits_router

# ============================================================
# 新增：政策查询、学区查询、升学日历、升学黑话路由模块
# ============================================================
from app.policy_routes import router as policy_router
from app.district_routes import router as district_router
from app.calendar_routes import router as calendar_router
from app.jargon_routes import router as jargon_router

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
# 应用初始化
# ============================================================
app = FastAPI(
    title="K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋",
    description="四步裁决引擎 + 配额系统 + 黑话翻译 + 微信OAuth + 按次诊断计费",
    version="2.0.0",
    docs_url="/docs" if K12_ENV != "production" else None,
    redoc_url="/redoc" if K12_ENV != "production" else None,
)

# ============================================================
# 中间件配置
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if K12_ENV == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[K12_HOST, "localhost", "127.0.0.1"],
    )

# ============================================================
# 限流器
# ============================================================
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================================
# 注册路由
# ============================================================
app.include_router(wechat_router, prefix="/api/wechat", tags=["微信OAuth"])
app.include_router(payment_router, prefix="/api/payment", tags=["支付模块"])
app.include_router(credits_router, prefix="/api/credits", tags=["积分模块"])
app.include_router(policy_router, prefix="/api/policy", tags=["政策查询"])
app.include_router(district_router, prefix="/api/district", tags=["学区查询"])
app.include_router(calendar_router, prefix="/api/calendar", tags=["升学日历"])
app.include_router(jargon_router, prefix="/api/jargon", tags=["升学黑话"])


# ============================================================
# 静态文件挂载
# ============================================================
static_dir = PROJECT_ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info(f"静态文件目录已挂载: {static_dir}")
else:
    logger.warning(f"静态文件目录不存在: {static_dir}")


# ============================================================
# 健康检查端点
# ============================================================
@app.get("/health", response_model=HealthResponse, tags=["系统"])
async def health_check():
    """系统健康检查"""
    return HealthResponse(
        status="ok",
        version="2.0.0",
        timestamp=datetime.utcnow().isoformat(),
        env=K12_ENV,
    )


# ============================================================
# 诊断端点（核心功能）
# ============================================================
@app.post("/api/diagnose", response_model=DiagnosisResult, tags=["诊断"])
@limiter.limit("10/minute")
async def diagnose(request: Request, diagnosis_req: DiagnosisRequest):
    """
    升学诊断 - 按次计费
    每次诊断消耗1次配额，配额不足时返回错误
    """
    try:
        # 获取用户信息
        openid = request.headers.get("X-WeChat-OpenID", "")
        if not openid:
            raise HTTPException(status_code=401, detail="未授权，缺少微信OpenID")

        # 检查配额
        user = get_or_create_user(openid)
        if user.remaining_quota <= 0:
            raise HTTPException(
                status_code=402,
                detail="配额不足，请购买诊断次数",
                headers={"X-Quota-Exhausted": "true"},
            )

        # 执行诊断
        result = generate_diagnosis(diagnosis_req)

        # 扣除配额
        user.remaining_quota -= 1
        user.save()

        # 记录诊断日志
        logger.info(f"用户 {openid} 完成诊断，剩余配额: {user.remaining_quota}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"诊断失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="诊断服务异常")


# ============================================================
# 黑话翻译端点
# ============================================================
@app.post("/api/translate", response_model=JargonResult, tags=["黑话翻译"])
@limiter.limit("30/minute")
async def translate(request: Request, jargon_req: JargonRequest):
    """升学黑话翻译"""
    try:
        result = translate_jargon(jargon_req.text)
        return result
    except Exception as e:
        logger.error(f"翻译失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="翻译服务异常")


# ============================================================
# 反馈端点
# ============================================================
@app.post("/api/feedback", tags=["反馈"])
@limiter.limit("5/minute")
async def submit_feedback(request: Request, feedback: FeedbackRequest):
    """提交用户反馈"""
    try:
        # 保存反馈到数据库或文件
        feedback_dir = PROJECT_ROOT / "data" / "feedback"
        feedback_dir.mkdir(parents=True, exist_ok=True)

        feedback_file = feedback_dir / f"feedback_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.json"
        with open(feedback_file, "w", encoding="utf-8") as f:
            json.dump(feedback.dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"反馈已保存: {feedback_file}")
        return {"status": "ok", "message": "感谢您的反馈！"}

    except Exception as e:
        logger.error(f"保存反馈失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="反馈提交失败")


# ============================================================
# 配额查询端点
# ============================================================
@app.get("/api/quota", tags=["配额"])
async def get_quota(request: Request):
    """查询当前用户配额"""
    try:
        openid = request.headers.get("X-WeChat-OpenID", "")
        if not openid:
            raise HTTPException(status_code=401, detail="未授权")

        user = get_or_create_user(openid)
        return {
            "openid": openid,
            "remaining_quota": user.remaining_quota,
            "total_quota": user.total_quota,
            "plan": user.plan.value if hasattr(user, 'plan') else "free",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询配额失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询配额失败")


# ============================================================
# 微信支付回调通知
# ============================================================
@app.post("/api/payment/notify", tags=["支付"])
async def payment_notify(request: Request):
    """
    微信支付结果通知回调
    接收微信服务器发送的支付结果通知
    """
    try:
        # 获取请求体
        body = await request.body()
        body_str = body.decode("utf-8")

        # 解析微信回调通知
        from app.payment import parse_wechat_notification
        result = parse_wechat_notification(body_str)

        if result.get("event_type") == "TRANSACTION.SUCCESS":
            # 处理支付成功
            resource = result.get("resource", {})
            decrypt_result = decrypt_wechat_resource(resource)

            if decrypt_result:
                handle_payment_success(decrypt_result)
                logger.info(f"支付成功处理完成: {decrypt_result.get('out_trade_no')}")
            else:
                logger.error("支付回调解密失败")

        # 返回成功响应给微信服务器
        return {"code": "SUCCESS", "message": "成功"}

    except Exception as e:
        logger.error(f"支付回调处理失败: {str(e)}", exc_info=True)
        # 返回失败响应，微信会重试
        return {"code": "FAIL", "message": "处理失败"}


# ============================================================
# 启动入口
# ============================================================
if __name__ == "__main__":
    logger.info(f"🚀 K12 Rocket v2.0 启动中...")
    logger.info(f"环境: {K12_ENV}")
    logger.info(f"监听: {K12_HOST}:{K12_PORT}")
    logger.info(f"微信支付: {'已启用' if WECHAT_PAY_APPID else '未配置(模拟模式)'}")

    uvicorn.run(
        "app.main:app",
        host=K12_HOST,
        port=K12_PORT,
        reload=(K12_ENV == "development"),
        log_level=K12_LOG_LEVEL,
    )
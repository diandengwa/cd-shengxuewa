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
        allowed_hosts=os.getenv("K12_TRUSTED_HOSTS", "localhost,127.0.0.1").split(","),
    )

# ============================================================
# 速率限制
# ============================================================
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================================
# 静态文件挂载
# ============================================================
static_dir = PROJECT_ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ============================================================
# 注册路由
# ============================================================

# 微信相关路由（OAuth + 支付回调）
app.include_router(wechat_router, prefix="/wechat", tags=["微信"])

# 支付相关路由（下单、查询、回调）
app.include_router(payment_router, prefix="/payment", tags=["支付"])

# 积分/配额相关路由
app.include_router(credits_router, prefix="/credits", tags=["积分"])

# 政策查询路由
app.include_router(policy_router, prefix="/policy", tags=["政策"])

# 学区查询路由
app.include_router(district_router, prefix="/district", tags=["学区"])

# 升学日历路由
app.include_router(calendar_router, prefix="/calendar", tags=["日历"])

# 升学黑话路由
app.include_router(jargon_router, prefix="/jargon", tags=["黑话"])


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
    )


# ============================================================
# 首页
# ============================================================
@app.get("/", response_class=HTMLResponse, tags=["系统"])
async def index():
    """返回首页"""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋</h1><p>系统运行中...</p>")


# ============================================================
# 诊断接口（核心功能）
# ============================================================
@app.post("/diagnose", response_model=DiagnosisResult, tags=["诊断"])
@limiter.limit("10/minute")
async def diagnose(request: Request, diagnosis_req: DiagnosisRequest):
    """
    升学诊断接口
    - 需要微信登录（通过 openid 识别用户）
    - 每次诊断消耗 1 次配额
    """
    # 获取用户 openid（从请求头或 session）
    openid = request.headers.get("X-OpenID", "")
    if not openid:
        raise HTTPException(status_code=401, detail="请先通过微信登录")

    # 检查配额
    quota_check = await check_quota(openid)
    if not quota_check["has_quota"]:
        raise HTTPException(
            status_code=402,
            detail={
                "message": "配额不足，请购买诊断次数",
                "remaining": quota_check["remaining"],
                "needs_payment": True,
            },
        )

    # 执行诊断
    try:
        result = await generate_diagnosis(diagnosis_req)
        return result
    except Exception as e:
        logger.error(f"诊断失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="诊断服务异常，请稍后重试")


# ============================================================
# 黑话翻译接口
# ============================================================
@app.post("/translate", response_model=JargonResult, tags=["黑话"])
@limiter.limit("30/minute")
async def translate(request: Request, jargon_req: JargonRequest):
    """升学黑话翻译接口"""
    try:
        result = await translate_jargon(jargon_req.text)
        return result
    except Exception as e:
        logger.error(f"翻译失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="翻译服务异常")


# ============================================================
# 反馈接口
# ============================================================
@app.post("/feedback", tags=["系统"])
@limiter.limit("10/minute")
async def submit_feedback(request: Request, feedback: FeedbackRequest):
    """用户反馈提交"""
    try:
        # 保存反馈到数据库或日志
        feedback_data = feedback.dict()
        feedback_data["timestamp"] = datetime.now().isoformat()
        feedback_data["ip"] = request.client.host
        
        feedback_file = logs_dir / "feedback.jsonl"
        with open(feedback_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(feedback_data, ensure_ascii=False) + "\n")
        
        logger.info(f"收到用户反馈: {feedback_data}")
        return {"status": "ok", "message": "感谢您的反馈！"}
    except Exception as e:
        logger.error(f"保存反馈失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="反馈提交失败")


# ============================================================
# 启动入口
# ============================================================
if __name__ == "__main__":
    logger.info(f"🚀 K12 Rocket v2.0 启动中...")
    logger.info(f"  环境: {K12_ENV}")
    logger.info(f"  地址: http://{K12_HOST}:{K12_PORT}")
    logger.info(f"  微信支付: {'已配置' if WECHAT_PAY_APPID else '未配置（使用模拟模式）'}")
    logger.info(f"  文档: http://{K12_HOST}:{K12_PORT}/docs")
    
    uvicorn.run(
        "app.main:app",
        host=K12_HOST,
        port=K12_PORT,
        reload=(K12_ENV == "development"),
        log_level=K12_LOG_LEVEL,
    )
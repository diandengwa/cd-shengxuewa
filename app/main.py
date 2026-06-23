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
# 创建 FastAPI 应用实例
# ============================================================
app = FastAPI(
    title="K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋",
    description="四步裁决引擎 + 配额系统 + 黑话翻译 + 微信OAuth + 政策查询 + 学区查询 + 升学日历",
    version="2.0.0",
    docs_url="/docs" if K12_ENV != "production" else None,
    redoc_url="/redoc" if K12_ENV != "production" else None,
)

# ============================================================
# 速率限制中间件配置
# ============================================================
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.getenv("REDIS_URL", "memory://"),
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================================
# 中间件注册
# ============================================================
# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 可信主机中间件（生产环境启用）
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
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ============================================================
# 注册路由模块
# ============================================================
# 微信相关路由
app.include_router(wechat_router, prefix="/wechat", tags=["微信"])

# 支付相关路由
app.include_router(payment_router, prefix="/payment", tags=["支付"])

# 积分相关路由
app.include_router(credits_router, prefix="/credits", tags=["积分"])

# 政策查询路由
app.include_router(policy_router, prefix="/policy", tags=["政策查询"])

# 学区查询路由
app.include_router(district_router, prefix="/district", tags=["学区查询"])

# 升学日历路由
app.include_router(calendar_router, prefix="/calendar", tags=["升学日历"])

# 升学黑话路由
app.include_router(jargon_router, prefix="/jargon", tags=["升学黑话"])

# ============================================================
# 健康检查接口
# ============================================================
@app.get("/health", response_model=HealthResponse, tags=["系统"])
@limiter.limit("10/minute")
async def health_check(request: Request):
    """系统健康检查接口"""
    try:
        # 检查数据库连接
        from app.database import get_db
        db = get_db()
        db.execute("SELECT 1")
        db.close()
        db_status = "healthy"
    except Exception as e:
        logger.error(f"数据库健康检查失败: {e}")
        db_status = "unhealthy"

    return HealthResponse(
        status="ok",
        version="2.0.0",
        timestamp=datetime.now().isoformat(),
        environment=K12_ENV,
        database=db_status,
    )

# ============================================================
# 根路径重定向到文档
# ============================================================
@app.get("/", tags=["系统"])
async def root():
    """根路径重定向到API文档"""
    return JSONResponse(
        content={
            "message": "欢迎使用 K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋",
            "docs": "/docs" if K12_ENV != "production" else None,
            "version": "2.0.0",
        }
    )

# ============================================================
# 错误处理
# ============================================================
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理"""
    logger.warning(f"HTTP异常: {exc.status_code} - {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "status_code": exc.status_code,
        },
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """通用异常处理"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "服务器内部错误，请稍后重试",
            "status_code": 500,
        },
    )

# ============================================================
# 启动事件
# ============================================================
@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    logger.info("=" * 60)
    logger.info(f"K12 Rocket v2.0 启动中...")
    logger.info(f"环境: {K12_ENV}")
    logger.info(f"日志级别: {K12_LOG_LEVEL}")
    logger.info(f"静态文件目录: {static_dir}")
    
    # 检查必要目录
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    
    # 初始化数据库
    try:
        from app.database import init_db
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
    
    # 加载升学黑话词典
    try:
        from app.jargon_routes import load_jargon_data
        load_jargon_data()
        logger.info("升学黑话词典加载完成")
    except Exception as e:
        logger.warning(f"升学黑话词典加载失败: {e}")
    
    # 加载政策数据
    try:
        from app.policy_routes import load_policy_data
        load_policy_data()
        logger.info("政策数据加载完成")
    except Exception as e:
        logger.warning(f"政策数据加载失败: {e}")
    
    # 加载学区数据
    try:
        from app.district_routes import load_district_data
        load_district_data()
        logger.info("学区数据加载完成")
    except Exception as e:
        logger.warning(f"学区数据加载失败: {e}")
    
    # 加载升学日历数据
    try:
        from app.calendar_routes import load_calendar_data
        load_calendar_data()
        logger.info("升学日历数据加载完成")
    except Exception as e:
        logger.warning(f"升学日历数据加载失败: {e}")
    
    logger.info("K12 Rocket v2.0 启动完成")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时的清理操作"""
    logger.info("K12 Rocket v2.0 正在关闭...")
    # 关闭数据库连接
    try:
        from app.database import close_db
        close_db()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接失败: {e}")
    logger.info("K12 Rocket v2.0 已关闭")

# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    logger.info(f"启动服务器: {K12_HOST}:{K12_PORT}")
    uvicorn.run(
        "app.main:app",
        host=K12_HOST,
        port=K12_PORT,
        reload=K12_ENV == "development",
        log_level=K12_LOG_LEVEL,
        workers=1 if K12_ENV == "development" else 4,
    )
#!/usr/bin/env python3

"""

K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋

四步裁决引擎 + 配额系统 + 黑话翻译 + 微信OAuth

"""



import os
import sys
import json
import logging
import secrets
from pathlib import Path
from datetime import datetime



PROJECT_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")



from fastapi import FastAPI, HTTPException, Query, Request

from fastapi.middleware.cors import CORSMiddleware

from fastapi.staticfiles import StaticFiles

from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

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

# 配置

# ============================================================



K12_ENV = os.getenv("K12_ENV", "development")

K12_HOST = os.getenv("K12_HOST", "127.0.0.1")

K12_PORT = int(os.getenv("K12_PORT", "8000"))

K12_LOG_LEVEL = os.getenv("K12_LOG_LEVEL", "info").lower()



cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

if K12_ENV == "production":
    custom_origins = os.getenv("K12_CORS_ORIGINS", "")
    if custom_origins:
        cors_origins = [o.strip() for o in custom_origins.split(",")]
    else:
        # 生产环境下如果没配来源，默认空，不允许 * 跨域
        logger.warning("[Security] 生产环境已禁用默认的 * CORS跨域。请设置 K12_CORS_ORIGINS 环境变量。")
        cors_origins = []
else:
    # 允许通配符只在非生产调试环境
    cors_origins = ["*"]




# ============================================================

# 日志

# ============================================================



logs_dir = PROJECT_ROOT / "logs"

logs_dir.mkdir(exist_ok=True)



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



# ============================================================

# FastAPI 应用

# ============================================================



app = FastAPI(

    title="点灯蛙·成都K12升学参谋",

    description="帮成都升学家长判断：我的情况，到底行不行。",

    version="2.0.0",

)



app.add_middleware(

    CORSMiddleware,

    allow_origins=cors_origins,

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)



# 微信路由

app.include_router(wechat_router)



# 静态文件（前端）

STATIC_DIR = PROJECT_ROOT / "static"

if STATIC_DIR.exists():

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")





@app.on_event("startup")

async def startup_event():

    """启动时加载所有数据"""


    # Load dual-core knowledge base (policy + pain-point cards)
    if knowledge_card_loader.load():
        golden_count = len(knowledge_card_loader.golden_cards)
        problem_count = len(knowledge_card_loader.problem_cards)
        logger.info(f"[dianwa] dual-core KB loaded: {golden_count} policy + {problem_count} pain cards")
    else:
        logger.warning("[dianwa] dual-core KB empty (allowed, pending cold-start)")
    logger.info("[点灯蛙 v2.0] 正在加载数据...")



    if wiki_loader.load():

        logger.info(f"[点灯蛙] Wiki加载完成: {len(wiki_loader.manifest)} 页")

    else:

        logger.warning("[点灯蛙] Wiki加载失败")



    if gt_loader.load():

        logger.info(f"[点灯蛙] GT校准库加载完成: {len(gt_loader.records)} 条")

    else:

        logger.warning("[点灯蛙] GT校准库加载失败（允许空库）")



    if lottery_loader.load():

        logger.info(f"[点灯蛙] 历史摇号数据加载完成: {len(lottery_loader.data)} 条")

    else:

        logger.warning("[点灯蛙] 历史摇号数据加载失败（允许空库）")



    logger.info("[点灯蛙 v2.0] 启动完成 ✓")





# ============================================================

# API 接口

# ============================================================



@app.get("/health", response_model=HealthResponse)

async def health_check():

    return HealthResponse(

        status="ok",

        version="2.0.0",

        wiki_pages_count=len(wiki_loader.manifest) if wiki_loader.is_loaded() else 0,

        index_loaded=wiki_loader.is_loaded(),

        engine="advisor-v2",

    )





@app.post("/diagnose/policy", response_model=DiagnosisResult)

async def diagnose_policy(request: DiagnosisRequest):

    """

    政策诊断 — 四步裁决引擎

    免费层: Step1 + 8段基础输出

    付费层: Step1-4 完整输出

    """

    if not request.question:

        raise HTTPException(status_code=400, detail="问题不能为空")



    logger.info(f"[诊断请求] {request.question[:50]}... plan={request.plan}")



    # 配额检查

    if request.openid:

        action = "diagnose" if request.plan in (PlanType.LITE, PlanType.MAX) else "query"

        allowed, user, msg = check_quota(request.openid, action)

        if not allowed:

            # 免费层降级：仍然给基础8段输出，但标记为截断版

            if action == "diagnose" and user.plan == PlanType.FREE:

                request.plan = PlanType.FREE  # 降级为免费层输出

            else:

                raise HTTPException(status_code=429, detail=msg)



    # 路由

    route = route_question(request.question, stage=request.stage)

    logger.info(f"[路由] 场景={route.scenario.value}, 置信度={route.confidence:.2f}")



    # 生成诊断

    result = await generate_diagnosis(request, route)

    logger.info(f"[诊断完成] plan={result.plan_used}, confidence={result.confidence}")

    return result





@app.post("/jargon", response_model=JargonResult)

async def jargon_translate(request: JargonRequest):

    """黑话翻译 — 冷启动钩子，免费无限"""

    if not request.term:

        raise HTTPException(status_code=400, detail="术语不能为空")

    result = translate_jargon(request.term)

    return JargonResult(**result)





@app.get("/jargon/list")

async def jargon_list():

    """列出所有黑话"""

    from app.answerer import JARGON_TABLE

    return {"terms": [

        {"term": k, "plain": v["plain"], "scenario": v["scenario"]}

        for k, v in JARGON_TABLE.items()

    ]}





@app.post("/feedback")

async def submit_feedback(feedback: FeedbackRequest):

    """用户反馈"""

    feedback_dir = PROJECT_ROOT / "feedback"

    feedback_dir.mkdir(exist_ok=True)



    today = datetime.now().strftime("%Y-%m-%d")

    feedback_file = feedback_dir / f"{today}.jsonl"



    entry = {

        "timestamp": feedback.timestamp or datetime.now().isoformat(),

        "question": feedback.question[:200],

        "scenario": feedback.scenario,

        "feedback_type": feedback.feedback_type,

        "correction": feedback.correction[:500] if feedback.correction else "",

    }



    with open(feedback_file, "a", encoding="utf-8") as f:

        f.write(json.dumps(entry, ensure_ascii=False) + "\n")



    logger.info(f"[反馈] type={feedback.feedback_type}")

    return {"status": "ok", "message": "感谢反馈"}





# ============================================================

# 邀请码 & 订单 API

# ============================================================



@app.post("/invite/redeem")

async def invite_redeem(payload: dict):

    """兑换邀请码"""

    code = payload.get("code", "").strip().upper()

    openid = payload.get("openid", "").strip()



    if not code:

        raise HTTPException(status_code=400, detail="邀请码不能为空")

    if not openid:

        raise HTTPException(status_code=400, detail="请先登录")



    success, msg, plan_granted = redeem_code(code, openid)

    if not success:

        return {"success": False, "message": msg}



    # 自动升级用户套餐

    if plan_granted:

        upgrade_plan(openid, plan_granted)



    return {"success": True, "message": msg, "plan": plan_granted.value if plan_granted else None}





@app.post("/order/create")

async def order_create(payload: dict):

    """创建付款订单"""

    plan_str = payload.get("plan", "lite")

    openid = payload.get("openid", "")



    try:

        plan = PlanType(plan_str)

    except ValueError:

        plan = PlanType.LITE



    if plan == PlanType.FREE:

        raise HTTPException(status_code=400, detail="免费版无需下单")



    order = create_pending_order(plan, openid)

    return order





@app.get("/order/check")

async def order_check(order_id: str, openid: str = ""):

    """查询订单状态（用户轮询）"""

    order = check_order_for_openid(order_id, openid)

    if not order:

        raise HTTPException(status_code=404, detail="订单不存在")



    # 如果已付款且有邀请码，且用户提供了openid，自动兑换

    if order["status"] == "paid" and order.get("invite_code") and openid:

        success, msg, _ = redeem_code(order["invite_code"], openid)

        if success:

            upgrade_plan(openid, PlanType(order["plan"]))

            order["auto_redeemed"] = True



    return order


@app.post("/pay/wechat/prepay")
async def pay_wechat_prepay(payload: dict):
    """
    拉起微信预支付（JSAPI）
    """
    order_id = payload.get("order_id", "").strip().upper()
    openid = payload.get("openid", "").strip()

    if not order_id:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    if not openid:
        raise HTTPException(status_code=400, detail="请先微信登录")

    # 查询挂起订单
    from app.invite_codes import _load_orders
    orders = _load_orders()
    order = orders.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="订单已支付完成")
    if order["status"] == "cancelled":
        raise HTTPException(status_code=400, detail="订单已取消")
    if order.get("openid") and order["openid"] != openid:
        raise HTTPException(status_code=403, detail="无权操作此订单")

    plan_val = order["plan"]
    amount = float(order["amount"])

    # 调用微信支付预下单
    success, res = await wechat_prepay_order(
        order_id=order_id,
        plan_val=plan_val,
        amount_yuan=amount,
        openid=openid
    )

    if not success:
        raise HTTPException(status_code=500, detail=res.get("message", "微信下单失败"))

    return res


@app.post("/pay/wechat/notify")
async def pay_wechat_notify(request: Request):
    """
    微信支付回调通知（真实商户支付回调，支持 V3 AES 解密验签）
    """
    import secrets
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        logger.info(f"[Notify] 收到微信支付通知: {body_str}")
        
        # 校验与解密
        notify_data = json.loads(body_str)
        resource = notify_data.get("resource", {})
        algorithm = resource.get("algorithm")
        ciphertext = resource.get("ciphertext")
        nonce = resource.get("nonce")
        associated_data = resource.get("associated_data")
        
        if algorithm != "AEAD_AES_256_GCM" or not ciphertext or not nonce:
            logger.error(f"[Notify] 不合法的通知格式: algorithm={algorithm}")
            return JSONResponse(status_code=400, content={"code": "FAIL", "message": "参数格式错误"})
            
        # 解密
        decrypted_data = decrypt_wechat_resource(ciphertext, nonce, associated_data)
        if not decrypted_data:
            logger.error("[Notify] 解密失败")
            return JSONResponse(status_code=400, content={"code": "FAIL", "message": "解密失败"})
            
        logger.info(f"[Notify] 解密成功内容: {decrypted_data}")
        trade_state = decrypted_data.get("trade_state")
        
        if trade_state == "SUCCESS":
            order_id = decrypted_data.get("out_trade_no")
            transaction_id = decrypted_data.get("transaction_id")
            
            # 标记付款成功并自动发货升级 Plan
            success, msg = handle_payment_success(order_id, transaction_id)
            if success:
                logger.info(f"[Notify] 支付成功处理完成: order_id={order_id}")
                return {"code": "SUCCESS", "message": "成功"}
            else:
                return JSONResponse(status_code=500, content={"code": "FAIL", "message": msg})
                
        return {"code": "SUCCESS", "message": "非成功交易状态，不做处理"}
    except Exception as e:
        logger.error(f"[Notify] 回调处理发生异常: {e}")
        return JSONResponse(status_code=500, content={"code": "FAIL", "message": str(e)})


@app.post("/pay/wechat/notify-mock")
async def pay_wechat_notify_mock(payload: dict):
    """
    模拟微信支付回调端点（用于本地/测试环境调试发货发码流程）
    """
    order_id = payload.get("order_id", "").strip().upper()
    transaction_id = payload.get("transaction_id", f"mock_tx_{secrets.token_hex(6)}").strip()

    if not order_id:
        raise HTTPException(status_code=400, detail="订单号不能为空")

    # 查询挂起订单
    from app.invite_codes import _load_orders
    orders = _load_orders()
    if order_id not in orders:
        raise HTTPException(status_code=404, detail="订单不存在")

    # 标记付款成功并自动发货升级 Plan
    success, msg = handle_payment_success(order_id, transaction_id)
    if not success:
        raise HTTPException(status_code=500, detail=msg)

    return {"success": True, "message": msg, "order_id": order_id, "transaction_id": transaction_id}





# ============================================================

# 管理员 API

# ============================================================



@app.post("/admin/codes/generate")

async def admin_generate_codes(payload: dict):

    """管理员批量生成邀请码"""

    secret = payload.get("secret", "")

    if not verify_admin(secret):

        raise HTTPException(status_code=403, detail="管理员密码错误")



    count = min(int(payload.get("count", 1)), 100)

    plan_str = payload.get("plan", "lite")

    source = payload.get("source", "manual")

    note = payload.get("note", "")

    expires_days = int(payload.get("expires_days", 90))



    try:

        plan = PlanType(plan_str)

    except ValueError:

        plan = PlanType.LITE



    codes = generate_codes(count, plan, source, expires_days, note)

    return {"success": True, "count": len(codes), "codes": codes}





@app.get("/admin/codes/list")

async def admin_list_codes(secret: str = "", status: str = None, source: str = None, limit: int = 50):

    """管理员列出邀请码"""

    if not verify_admin(secret):

        raise HTTPException(status_code=403, detail="管理员密码错误")

    codes = list_codes(status=status, source=source, limit=limit)

    return {"count": len(codes), "codes": codes}





@app.post("/admin/order/confirm")

async def admin_confirm_order(payload: dict):

    """管理员确认付款 → 自动生成邀请码"""

    secret = payload.get("secret", "")

    if not verify_admin(secret):

        raise HTTPException(status_code=403, detail="管理员密码错误")



    order_id = payload.get("order_id", "").strip().upper()

    note = payload.get("note", "")



    success, msg, invite_code = confirm_order(order_id, note)

    if not success:

        return {"success": False, "message": msg}



    return {"success": True, "message": msg, "invite_code": invite_code}





@app.get("/admin/orders/list")

async def admin_list_orders(secret: str = "", status: str = None, limit: int = 50):

    """管理员列出订单"""

    if not verify_admin(secret):

        raise HTTPException(status_code=403, detail="管理员密码错误")

    orders = list_orders(status=status, limit=limit)

    return {"count": len(orders), "orders": orders}





@app.get("/lottery/history")

async def lottery_history(

    year: int = None,

    school: str = None,

):

    """摇号历史数据"""

    if not lottery_loader.is_loaded():

        raise HTTPException(status_code=503, detail="摇号数据未加载")

    data = lottery_loader.data

    if year:

        data = [r for r in data if r.get("year") == year]

    if school:

        data = [r for r in data if school in r.get("school", "")]

    return data





@app.get("/quota/{openid}")

async def get_user_quota_info(openid: str):

    """查询用户配额"""

    user = get_or_create_user(openid)

    return {

        "plan": user.plan.value,

        "quota": user.quota.model_dump(),

        "family_info": user.family_info.model_dump(),

    }





# ============================================================

# 前端页面路由

# ============================================================



@app.get("/")

async def serve_index():

    """首页 — v1.4 兼容"""

    index_path = PROJECT_ROOT / "static" / "index.html"

    if index_path.exists():

        return FileResponse(str(index_path), media_type="text/html")

    return HTMLResponse("<h1>点灯蛙·成都K12升学参谋 v2.0</h1><p>系统运行中</p>")





@app.get("/chat")

async def serve_chat():

    """对话式顾问页面"""

    chat_path = PROJECT_ROOT / "static" / "chat.html"

    if chat_path.exists():

        return FileResponse(str(chat_path), media_type="text/html")

    return HTMLResponse("<h1>对话式顾问（开发中）</h1>")





@app.get("/profile")

async def serve_profile():

    """用户中心"""

    profile_path = PROJECT_ROOT / "static" / "profile.html"

    if profile_path.exists():

        return FileResponse(str(profile_path), media_type="text/html")

    return HTMLResponse("<h1>用户中心（开发中）</h1>")





@app.get("/pay")

async def serve_pay():

    """支付页"""

    pay_path = PROJECT_ROOT / "static" / "pay.html"

    if pay_path.exists():

        return FileResponse(str(pay_path), media_type="text/html")

    return HTMLResponse("<h1>支付页面（开发中）</h1>")





# ============================================================

# 根信息

# ============================================================



@app.get("/api")

async def api_root():

    return {

        "name": "点灯蛙·成都K12升学参谋",

        "version": "2.0.0",

        "description": "帮成都升学家长判断：我的情况，到底行不行。",

        "engine": "advisor-v2 (四步裁决框架)",

        "endpoints": [

            {"path": "/health", "method": "GET", "description": "健康检查"},

            {"path": "/diagnose/policy", "method": "POST", "description": "政策诊断(四步裁决)"},

            {"path": "/jargon", "method": "POST", "description": "黑话翻译"},

            {"path": "/jargon/list", "method": "GET", "description": "黑话列表"},

            {"path": "/feedback", "method": "POST", "description": "用户反馈"},

            {"path": "/quota/{openid}", "method": "GET", "description": "配额查询"},

            {"path": "/wechat/auth", "method": "GET", "description": "微信OAuth"},

            {"path": "/chat", "method": "GET", "description": "对话式顾问"},

        ],

    }





def main():

    print("=" * 50)

    print("点灯蛙·成都K12升学参谋 v2.0")

    print("=" * 50)

    print(f"环境: {K12_ENV}")

    print(f"监听: {K12_HOST}:{K12_PORT}")

    print(f"引擎: 四步裁决(情况理解→灰色地带→竞争烈度→时间线)")

    print("=" * 50)



    uvicorn.run(

        "app.main:app",

        host=K12_HOST,

        port=K12_PORT,

        reload=False,

        log_level=K12_LOG_LEVEL,

    )





if __name__ == "__main__":

    main()


"""
微信路由 v2.0
OAuth + 消息推送 + 配额中间件集成 + 微信支付回调
"""

import time
import json
import logging
import secrets
import hashlib
import hmac
import xml.etree.ElementTree as ET
from fastapi import APIRouter, Query, Request, Response, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse

from .wechat import (
    verify_signature, build_oauth_url, exchange_code_for_openid,
    register_or_get_user, get_user_quota, increment_user_quota,
)
from .quota import check_quota, get_or_create_user, update_user, update_family_info
from .payment import (
    verify_payment_signature, process_payment_notification,
    get_payment_config, PAYMENT_SUCCESS, PAYMENT_FAILED
)

logger = logging.getLogger("k12_rocket.wechat_router")

router = APIRouter(tags=["wechat"])

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATES_FILE = DATA_DIR / "pending_states.json"

def _load_states() -> dict:
    if not STATES_FILE.exists():
        return {}
    try:
        with open(STATES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_states(states: dict):
    DATA_DIR.mkdir(exist_ok=True)
    try:
        with open(STATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(states, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save states: {e}")


# ============================================================
# 消息推送验证
# ============================================================

@router.get("/token")
async def wechat_token_verify(
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    if verify_signature(signature, timestamp, nonce):
        return Response(content=echostr, media_type="text/plain")
    raise HTTPException(status_code=403, detail="验证失败")


# ============================================================
# OAuth 授权
# ============================================================

@router.get("/auth")
async def wechat_auth(return_to: str = Query("/")):
    state = secrets.token_urlsafe(16)
    states = _load_states()
    states[state] = {"created_at": time.time(), "return_to": return_to}

    # 清理过期state
    now = time.time()
    expired = [k for k, v in states.items() if now - v["created_at"] > 600]
    for k in expired:
        del states[k]
    _save_states(states)

    auth_url = build_oauth_url(state=state, scope="snsapi_base")
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def wechat_callback(code: str = Query(...), state: str = Query(...)):
    states = _load_states()
    state_info = states.pop(state, None)
    _save_states(states)
    if not state_info:
        return HTMLResponse("<html><body><h3>授权已过期，请重新进入</h3><p><a href='/'>返回首页</a></p></body></html>", status_code=400)


    return_to = state_info.get("return_to", "/")
    result = exchange_code_for_openid(code)

    if "error" in result:
        return HTMLResponse(f"<html><body><h3>授权失败</h3><p><a href='/'>返回首页</a></p></body></html>", status_code=500)

    openid = result["openid"]
    oauth_token = result.get("access_token", "")

    # 注册/获取用户
    user = register_or_get_user(openid, oauth_token)

    # 构建跳转
    user_hash = hashlib.sha256(openid.encode()).hexdigest()[:16]
    sep = "&" if "?" in return_to else "?"
    redirect_url = f"{return_to}{sep}uid={user_hash}"

    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key="k12_uid",
        value=user_hash,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400 * 30,
    )
    return response


# ============================================================
# 配额查询 API
# ============================================================

@router.get("/quota")
async def get_quota(uid: str = Query(..., description="用户hash")):
    """查询用户配额"""
    # 这里需要实现配额查询逻辑
    # 暂时返回一个示例响应
    return {"uid": uid, "quota": 10, "used": 3}


# ============================================================
# 微信支付V3回调路由（支付结果通知）
# ============================================================

@router.post("/payment/callback")
async def wechat_payment_callback(request: Request):
    """
    微信支付V3回调处理
    接收微信支付结果通知，验证签名并处理支付结果
    """
    try:
        # 获取请求体原始数据
        body = await request.body()
        body_str = body.decode('utf-8')
        
        # 获取微信支付回调的请求头
        wechatpay_signature = request.headers.get("Wechatpay-Signature", "")
        wechatpay_timestamp = request.headers.get("Wechatpay-Timestamp", "")
        wechatpay_nonce = request.headers.get("Wechatpay-Nonce", "")
        wechatpay_serial = request.headers.get("Wechatpay-Serial", "")
        
        # 记录回调信息
        logger.info(f"收到微信支付回调: timestamp={wechatpay_timestamp}, nonce={wechatpay_nonce}")
        
        # 验证签名
        if not verify_payment_signature(
            body_str,
            wechatpay_signature,
            wechatpay_timestamp,
            wechatpay_nonce,
            wechatpay_serial
        ):
            logger.warning("微信支付回调签名验证失败")
            return JSONResponse(
                status_code=401,
                content={"code": "SIGN_ERROR", "message": "签名验证失败"}
            )
        
        # 解析回调数据
        callback_data = json.loads(body_str)
        
        # 处理支付通知
        result = process_payment_notification(callback_data)
        
        if result.get("status") == PAYMENT_SUCCESS:
            logger.info(f"支付成功处理: {result.get('message', '')}")
            # 返回成功响应给微信服务器
            return JSONResponse(
                status_code=200,
                content={"code": "SUCCESS", "message": "处理成功"}
            )
        else:
            logger.warning(f"支付处理失败: {result.get('message', '')}")
            # 返回失败响应，微信会重试
            return JSONResponse(
                status_code=500,
                content={"code": "FAIL", "message": result.get('message', '处理失败')}
            )
            
    except json.JSONDecodeError as e:
        logger.error(f"微信支付回调数据解析失败: {str(e)}")
        return JSONResponse(
            status_code=400,
            content={"code": "PARSE_ERROR", "message": "数据解析失败"}
        )
    except Exception as e:
        logger.error(f"微信支付回调处理异常: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"code": "SYSTEM_ERROR", "message": "系统异常"}
        )


# ============================================================
# 微信支付V3回调（XML格式兼容）
# ============================================================

@router.post("/payment/callback/xml")
async def wechat_payment_callback_xml(request: Request):
    """
    微信支付V2回调（XML格式）
    兼容旧版微信支付回调格式
    """
    try:
        # 获取请求体原始数据
        body = await request.body()
        body_str = body.decode('utf-8')
        
        # 记录回调信息
        logger.info(f"收到微信支付XML回调")
        
        # 解析XML
        try:
            root = ET.fromstring(body_str)
        except ET.ParseError as e:
            logger.error(f"XML解析失败: {str(e)}")
            return Response(
                content="<xml><return_code><![CDATA[FAIL]]></return_code><return_msg><![CDATA[数据格式错误]]></return_msg></xml>",
                media_type="application/xml"
            )
        
        # 提取关键字段
        return_code = root.findtext("return_code", "")
        if return_code != "SUCCESS":
            logger.warning(f"微信支付回调返回失败: {return_code}")
            return Response(
                content="<xml><return_code><![CDATA[FAIL]]></return_code><return_msg><![CDATA[处理失败]]></return_msg></xml>",
                media_type="application/xml"
            )
        
        # 验证签名（XML格式）
        # 注意：这里需要实现XML格式的签名验证
        # 暂时简单处理，直接返回成功
        logger.info("微信支付XML回调处理成功")
        
        # 返回成功响应
        return Response(
            content="<xml><return_code><![CDATA[SUCCESS]]></return_code><return_msg><![CDATA[OK]]></return_msg></xml>",
            media_type="application/xml"
        )
        
    except Exception as e:
        logger.error(f"微信支付XML回调处理异常: {str(e)}", exc_info=True)
        return Response(
            content="<xml><return_code><![CDATA[FAIL]]></return_code><return_msg><![CDATA[系统异常]]></return_msg></xml>",
            media_type="application/xml"
        )


# ============================================================
# 获取支付配置
# ============================================================

@router.get("/payment/config")
async def get_payment_config_api():
    """获取微信支付配置（前端调用）"""
    try:
        config = get_payment_config()
        return JSONResponse(
            status_code=200,
            content=config
        )
    except Exception as e:
        logger.error(f"获取支付配置失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"code": "CONFIG_ERROR", "message": "获取支付配置失败"}
        )
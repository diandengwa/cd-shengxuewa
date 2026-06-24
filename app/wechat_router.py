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

router = APIRouter(prefix="/wechat", tags=["wechat"])

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
    """查询用户配额状态"""
    # MVP: 用uid hash反查（实际应从cookie/session获取openid）
    # 这里简化处理，前端传uid hash
    return {"uid": uid, "message": "请通过微信登录后查询"}


# ============================================================
# 微信支付回调
# ============================================================

@router.post("/payment/callback")
async def wechat_payment_callback(request: Request):
    """
    微信支付结果通知回调
    接收微信服务器异步通知，处理支付结果
    """
    try:
        # 获取原始请求体（XML格式）
        body = await request.body()
        xml_data = body.decode('utf-8')
        
        logger.info(f"收到微信支付回调: {xml_data[:200]}...")
        
        # 解析XML
        root = ET.fromstring(xml_data)
        
        # 提取关键字段
        return_code = root.find('return_code').text if root.find('return_code') is not None else ''
        result_code = root.find('result_code').text if root.find('result_code') is not None else ''
        
        # 验证签名
        if not verify_payment_signature(xml_data):
            logger.warning("支付回调签名验证失败")
            return Response(
                content='<xml><return_code><![CDATA[FAIL]]></return_code><return_msg><![CDATA[签名失败]]></return_msg></xml>',
                media_type='application/xml'
            )
        
        # 处理支付结果
        if return_code == 'SUCCESS' and result_code == 'SUCCESS':
            # 支付成功，处理业务逻辑
            openid = root.find('openid').text if root.find('openid') is not None else ''
            transaction_id = root.find('transaction_id').text if root.find('transaction_id') is not None else ''
            out_trade_no = root.find('out_trade_no').text if root.find('out_trade_no') is not None else ''
            total_fee = int(root.find('total_fee').text) if root.find('total_fee') is not None else 0
            time_end = root.find('time_end').text if root.find('time_end') is not None else ''
            
            # 调用支付处理函数
            success = process_payment_notification(
                openid=openid,
                transaction_id=transaction_id,
                out_trade_no=out_trade_no,
                total_fee=total_fee,
                time_end=time_end
            )
            
            if success:
                logger.info(f"支付回调处理成功: 订单{out_trade_no}, 金额{total_fee}分")
                return Response(
                    content='<xml><return_code><![CDATA[SUCCESS]]></return_code><return_msg><![CDATA[OK]]></return_msg></xml>',
                    media_type='application/xml'
                )
            else:
                logger.error(f"支付回调处理失败: 订单{out_trade_no}")
                return Response(
                    content='<xml><return_code><![CDATA[FAIL]]></return_code><return_msg><![CDATA[处理失败]]></return_msg></xml>',
                    media_type='application/xml'
                )
        else:
            # 支付失败
            err_code = root.find('err_code').text if root.find('err_code') is not None else ''
            err_code_des = root.find('err_code_des').text if root.find('err_code_des') is not None else ''
            logger.warning(f"支付失败: {err_code} - {err_code_des}")
            
            return Response(
                content='<xml><return_code><![CDATA[SUCCESS]]></return_code><return_msg><![CDATA[OK]]></return_msg></xml>',
                media_type='application/xml'
            )
            
    except ET.ParseError as e:
        logger.error(f"XML解析失败: {e}")
        return Response(
            content='<xml><return_code><![CDATA[FAIL]]></return_code><return_msg><![CDATA[XML解析失败]]></return_msg></xml>',
            media_type='application/xml'
        )
    except Exception as e:
        logger.error(f"支付回调处理异常: {e}", exc_info=True)
        return Response(
            content='<xml><return_code><![CDATA[FAIL]]></return_code><return_msg><![CDATA[系统异常]]></return_msg></xml>',
            media_type='application/xml'
        )


@router.get("/payment/callback")
async def wechat_payment_callback_get():
    """
    微信支付回调GET请求处理（用于微信服务器验证）
    """
    return Response(
        content='<xml><return_code><![CDATA[SUCCESS]]></return_code><return_msg><![CDATA[OK]]></return_msg></xml>',
        media_type='application/xml'
    )


# ============================================================
# 支付状态查询
# ============================================================

@router.get("/payment/status/{out_trade_no}")
async def get_payment_status(out_trade_no: str):
    """
    查询支付订单状态
    """
    try:
        from .payment import get_payment_status as query_payment_status
        status = query_payment_status(out_trade_no)
        return JSONResponse(content={
            "code": 0,
            "message": "success",
            "data": status
        })
    except Exception as e:
        logger.error(f"查询支付状态失败: {e}")
        return JSONResponse(
            content={
                "code": -1,
                "message": f"查询失败: {str(e)}"
            },
            status_code=500
        )
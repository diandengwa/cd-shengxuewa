"""
微信路由 v2.0
OAuth + 消息推送 + 配额中间件集成
"""

import time
import json
import logging
import secrets
import hashlib
from fastapi import APIRouter, Query, Request, Response, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse

from .wechat import (
    verify_signature, build_oauth_url, exchange_code_for_openid,
    register_or_get_user, get_user_quota, increment_user_quota,
)
from .quota import check_quota, get_or_create_user, update_user, update_family_info

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
# 用户画像 API
# ============================================================

@router.post("/profile")
async def update_profile(request: Request):
    """更新用户家庭画像"""
    try:
        body = await request.json()
        openid = body.get("openid", "")
        if not openid:
            raise HTTPException(status_code=400, detail="需要openid")

        # 鉴权校验：防篡改他人画像
        k12_uid = request.cookies.get("k12_uid")
        if not k12_uid:
            raise HTTPException(status_code=401, detail="未登录或Cookie已失效")
            
        import hashlib
        expected_hash = hashlib.sha256(openid.encode()).hexdigest()[:16]
        if k12_uid != expected_hash:
            raise HTTPException(status_code=403, detail="无权修改该家庭画像")

        from .models import FamilyInfo
        family_data = body.get("family_info", {})
        family_info = FamilyInfo(**family_data)

        user = update_family_info(openid, family_info)
        return {"status": "ok", "family_info": user.family_info.model_dump()}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"[Profile] 更新失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))


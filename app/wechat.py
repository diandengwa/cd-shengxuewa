"""
微信 OAuth2.0 模块 v2.0
复用v1核心 + 增强用户管理集成
"""

import hashlib
import time
import json
import logging
import httpx
from pathlib import Path
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger("k12_rocket.wechat")

# 配置
WECHAT_APPID = os.getenv("WECHAT_APPID", "wx4a4643885e6b8a57") if (os := __import__('os')) else "wx4a4643885e6b8a57"
WECHAT_SECRET = os.getenv("WECHAT_SECRET", "c1802d103944ec7c9a5b88ec406eb991") if (os := __import__('os')) else "c1802d103944ec7c9a5b88ec406eb991"
WECHAT_TOKEN = os.getenv("WECHAT_TOKEN", "aecbcd1ca09fb7e316dd4ca5186808c4") if (os := __import__('os')) else "aecbcd1ca09fb7e316dd4ca5186808c4"

BASE_URL = os.getenv("BASE_URL", "https://cdk12edu.online") if (os := __import__('os')) else "https://cdk12edu.online"
OAUTH_REDIRECT_PATH = "/api/wechat/callback"
OAUTH_REDIRECT_URI = f"{BASE_URL}{OAUTH_REDIRECT_PATH}"

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
TOKEN_CACHE_FILE = DATA_DIR / "wechat_token_cache.json"


def verify_signature(signature: str, timestamp: str, nonce: str) -> bool:
    """验证微信消息推送签名"""
    params = sorted([WECHAT_TOKEN, timestamp, nonce])
    hash_str = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()
    return hash_str == signature


# access_token 缓存
_cached_access_token: Optional[str] = None
_cached_token_expires: float = 0


def get_access_token() -> str:
    """获取全局 access_token（带缓存，2小时有效）"""
    global _cached_access_token, _cached_token_expires

    if _cached_access_token and time.time() < _cached_token_expires - 300:
        return _cached_access_token

    if TOKEN_CACHE_FILE.exists():
        try:
            cache = json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() < cache.get("expires_at", 0) - 300:
                _cached_access_token = cache["access_token"]
                _cached_token_expires = cache["expires_at"]
                return _cached_access_token
        except (json.JSONDecodeError, KeyError):
            pass

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get("https://api.weixin.qq.com/cgi-bin/token", params={
                "grant_type": "client_credential",
                "appid": WECHAT_APPID,
                "secret": WECHAT_SECRET,
            })
            data = resp.json()
        if "access_token" in data:
            _cached_access_token = data["access_token"]
            _cached_token_expires = time.time() + data.get("expires_in", 7200)
            TOKEN_CACHE_FILE.write_text(json.dumps({
                "access_token": _cached_access_token,
                "expires_at": _cached_token_expires,
            }), encoding="utf-8")
            logger.info("[WeChat] access_token 刷新成功")
            return _cached_access_token
        else:
            logger.error(f"[WeChat] access_token 获取失败: {data}")
            raise Exception(f"获取access_token失败: {data.get('errmsg', 'unknown')}")
    except httpx.HTTPError as e:
        logger.error(f"[WeChat] access_token 请求异常: {e}")
        raise


def build_oauth_url(state: str = "", scope: str = "snsapi_base") -> str:
    """构建OAuth授权URL"""
    redirect_uri = quote(OAUTH_REDIRECT_URI, safe="")
    return (
        f"https://open.weixin.qq.com/connect/oauth2/authorize"
        f"?appid={WECHAT_APPID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&state={state}#wechat_redirect"
    )


def exchange_code_for_openid(code: str) -> dict:
    """用code换取openid"""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get("https://api.weixin.qq.com/sns/oauth2/access_token", params={
                "appid": WECHAT_APPID,
                "secret": WECHAT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
            })
            data = resp.json()
        if "openid" in data:
            return data
        else:
            logger.error(f"[WeChat] OAuth失败: {data}")
            return {"error": data.get("errmsg", "unknown"), "error_code": data.get("errcode", -1)}
    except httpx.HTTPError as e:
        logger.error(f"[WeChat] OAuth请求异常: {e}")
        return {"error": str(e)}


def register_or_get_user(openid: str, oauth_token: str = "") -> dict:
    """注册或获取用户 — 集成quota模块"""
    from .quota import get_or_create_user
    user = get_or_create_user(openid)
    user.last_active = time.strftime("%Y-%m-%dT%H:%M:%S")
    from .quota import update_user
    update_user(user)
    return user.model_dump()


def get_user_quota(openid: str) -> dict:
    """获取用户配额"""
    from .quota import get_or_create_user
    user = get_or_create_user(openid)
    return user.quota.model_dump()


def increment_user_quota(openid: str) -> dict:
    """增加用户查询计数"""
    from .quota import check_quota
    allowed, user, msg = check_quota(openid, "query")
    return {"allowed": allowed, "message": msg, "quota": user.quota.model_dump()}

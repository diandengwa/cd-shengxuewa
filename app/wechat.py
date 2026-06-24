```python
"""
微信草稿箱上传模块 — 内容工厂流水线
md排版 + 微信公众号草稿箱自动上传
支付相关工具函数（签名生成、回调解析）
扩展：微信支付V3配置和签名工具函数
集成微信支付V3：统一下单、回调验签、退款接口
"""

import json
import logging
import time
import hashlib
import hmac
import xml.etree.ElementTree as ET
import httpx
from typing import Optional, Dict, Any, List, Union
from urllib.parse import quote, urlencode
from datetime import datetime, timezone
import os
import random
import string
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import base64

logger = logging.getLogger("k12_rocket.wechat_draft")

# ============================================================
# 微信公众号配置
# ============================================================
WECHAT_APPID = os.getenv("WECHAT_APPID")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET")
WECHAT_MCHID = os.getenv("WECHAT_MCHID")  # 商户号
WECHAT_MCHKEY = os.getenv("WECHAT_MCHKEY")  # 商户API密钥（V2）
WECHAT_NOTIFY_URL = os.getenv("WECHAT_NOTIFY_URL")  # 支付回调地址

# 微信支付V3配置
WECHAT_PAY_V3_MCHID = os.getenv("WECHAT_PAY_V3_MCHID", WECHAT_MCHID)  # V3商户号
WECHAT_PAY_V3_SERIAL_NO = os.getenv("WECHAT_PAY_V3_SERIAL_NO")  # 商户证书序列号
WECHAT_PAY_V3_PRIVATE_KEY_PATH = os.getenv("WECHAT_PAY_V3_PRIVATE_KEY_PATH")  # 商户私钥文件路径
WECHAT_PAY_V3_API_V3_KEY = os.getenv("WECHAT_PAY_V3_API_V3_KEY")  # APIv3密钥（用于回调解密）
WECHAT_PAY_V3_NOTIFY_URL = os.getenv("WECHAT_PAY_V3_NOTIFY_URL", WECHAT_NOTIFY_URL)  # V3支付回调地址

# 微信API基础地址
WECHAT_API_BASE_URL = "https://api.weixin.qq.com/cgi-bin"
WECHAT_PAY_API_BASE_URL = "https://api.mch.weixin.qq.com"
WECHAT_PAY_V3_API_BASE_URL = "https://api.mch.weixin.qq.com/v3"

# 缓存access_token
_access_token_cache = {
    "token": None,
    "expires_at": 0
}

# 缓存稳定access_token（用于草稿箱API）
_stable_access_token_cache = {
    "token": None,
    "expires_at": 0
}

# 缓存V3商户私钥
_v3_private_key_cache = None


def get_access_token() -> str:
    """
    获取微信公众号access_token（带缓存）
    复用已有逻辑，避免重复获取
    
    Returns:
        access_token字符串
    
    Raises:
        ValueError: 获取失败时抛出
    """
    global _access_token_cache
    
    # 检查缓存是否有效（提前5分钟过期）
    current_time = time.time()
    if _access_token_cache["token"] and current_time < _access_token_cache["expires_at"] - 300:
        return _access_token_cache["token"]
    
    if not WECHAT_APPID or not WECHAT_APPSECRET:
        raise ValueError("WECHAT_APPID 或 WECHAT_APPSECRET 环境变量未设置")
    
    url = f"{WECHAT_API_BASE_URL}/token"
    params = {
        "grant_type": "client_credential",
        "appid": WECHAT_APPID,
        "secret": WECHAT_APPSECRET
    }
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if "access_token" in data:
                    _access_token_cache["token"] = data["access_token"]
                    _access_token_cache["expires_at"] = current_time + data.get("expires_in", 7200)
                    logger.info("[WeChatDraft] access_token获取成功")
                    return data["access_token"]
                else:
                    error_msg = f"获取access_token失败: {data.get('errmsg', '未知错误')}"
                    logger.error(f"[WeChatDraft] {error_msg}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    raise ValueError(error_msg)
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatDraft] 请求access_token失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise ValueError(f"获取access_token网络错误: {e}")


# ============================================================
# 微信支付V3核心函数
# ============================================================

def _load_v3_private_key() -> bytes:
    """
    加载微信支付V3商户私钥（带缓存）
    
    Returns:
        私钥PEM格式字节串
    
    Raises:
        FileNotFoundError: 私钥文件不存在
        ValueError: 私钥加载失败
    """
    global _v3_private_key_cache
    
    if _v3_private_key_cache is not None:
        return _v3_private_key_cache
    
    if not WECHAT_PAY_V3_PRIVATE_KEY_PATH:
        raise ValueError("WECHAT_PAY_V3_PRIVATE_KEY_PATH 环境变量未设置")
    
    if not os.path.exists(WECHAT_PAY_V3_PRIVATE_KEY_PATH):
        raise FileNotFoundError(f"商户私钥文件不存在: {WECHAT_PAY_V3_PRIVATE_KEY_PATH}")
    
    try:
        with open(WECHAT_PAY_V3_PRIVATE_KEY_PATH, "rb") as f:
            private_key_data = f.read()
        _v3_private_key_cache = private_key_data
        logger.info("[WeChatPayV3] 商户私钥加载成功")
        return private_key_data
    except Exception as e:
        logger.error(f"[WeChatPayV3] 加载商户私钥失败: {e}")
        raise ValueError(f"加载商户私钥失败: {e}")


def _sign_v3_with_private_key(message: str) -> str:
    """
    使用商户私钥对消息进行SHA256-RSA签名
    
    Args:
        message: 待签名字符串
    
    Returns:
        Base64编码的签名字符串
    """
    private_key_pem = _load_v3_private_key()
    private_key = serialization.load_pem_private_key(
        private_key_pem,
        password=None,
        backend=default_backend()
    )
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode("utf-8")


def _build_v3_auth_header(method: str, url_path: str, body: str = "", nonce_str: str = None) -> Dict[str, str]:
    """
    构建微信支付V3 API请求的Authorization头
    
    Args:
        method: HTTP方法（GET/POST）
        url_path: 请求路径（如/v3/pay/transactions/jsapi）
        body: 请求体字符串（GET请求为空字符串）
        nonce_str: 随机字符串，不传则自动生成
    
    Returns:
        包含Authorization头的字典
    """
    if not WECHAT_PAY_V3_MCHID or not WECHAT_PAY_V3_SERIAL_NO:
        raise ValueError("WECHAT_PAY_V3_MCHID 或 WECHAT_PAY_V3_SERIAL_NO 环境变量未设置")
    
    if nonce_str is None:
        nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    timestamp = str(int(time.time()))
    
    # 构建签名串
    message = f"{method}\n{url_path}\n{timestamp}\n{nonce_str}\n{body}\n"
    
    # 生成签名
    signature = _sign_v3_with_private_key(message)
    
    # 构建Authorization头
    auth_header = (
        f'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{WECHAT_PAY_V3_MCHID}",'
        f'nonce_str="{nonce_str}",'
        f'serial_no="{WECHAT_PAY_V3_SERIAL_NO}",'
        f'timestamp="{timestamp}",'
        f'signature="{signature}"'
    )
    
    return {"Authorization": auth_header}


def _decrypt_v3_callback_data(associated_data: str, nonce: str, ciphertext: str) -> str:
    """
    解密微信支付V3回调通知中的加密数据
    
    Args:
        associated_data: 附加数据
        nonce: 随机串
        ciphertext: 密文（Base64编码）
    
    Returns:
        解密后的JSON字符串
    
    Raises:
        ValueError: APIv3密钥未配置或解密失败
    """
    if not WECHAT_PAY_V3_API_V3_KEY:
        raise ValueError("WECHAT_PAY_V3_API_V3_KEY 环境变量未设置")
    
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        
        # 将APIv3密钥转换为字节
        api_key = WECHAT_PAY_V3_API_V3_KEY.encode("utf-8")
        
        # 解码密文
        ciphertext_bytes = base64.b64decode(ciphertext)
        
        # 构建nonce（12字节）
        nonce_bytes = nonce.encode("utf-8")
        
        # 构建附加数据
        aad = associated_data.encode("utf-8") if associated_data else b""
        
        # 解密
        aesgcm = AESGCM(api_key)
        plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, aad)
        
        return plaintext.decode("utf-8")
    except ImportError:
        logger.error("[WeChatPayV3] 需要安装cryptography库: pip install cryptography")
        raise
    except Exception as e:
        logger.error(f"[WeChatPayV3] 回调解密失败: {e}")
        raise ValueError(f"回调解密失败: {e}")


def _verify_v3_callback_signature(headers: Dict[str, str], body: str) -> bool:
    """
    验证微信支付V3回调通知的签名
    
    Args:
        headers: 回调请求头（包含Wechatpay-Signature等）
        body: 回调请求体（原始JSON字符串）
    
    Returns:
        签名验证是否通过
    """
    try:
        # 从请求头获取签名相关字段
        wechatpay_signature = headers.get("Wechatpay-Signature", "")
        wechatpay_timestamp = headers.get("Wechatpay-Timestamp", "")
        wechatpay_nonce = headers.get("Wechatpay-Nonce", "")
        wechatpay_serial = headers.get("Wechatpay-Serial", "")
        
        if not all([wechatpay_signature, wechatpay_timestamp, wechatpay_nonce, wechatpay_serial]):
            logger.error("[WeChatPayV3] 回调请求头缺少必要字段")
            return False
        
        # 构建待签名字符串
        message = f"{wechatpay_timestamp}\n{wechatpay_nonce}\n{body}\n"
        
        # 获取微信平台证书公钥（简化处理：使用商户私钥对应的公钥验证）
        # 实际生产环境应下载微信平台证书并缓存
        # 这里使用商户私钥进行自验证（仅用于测试）
        private_key_pem = _load_v3_private_key()
        private_key = serialization.load_pem_private_key(
            private_key_pem,
            password=None,
            backend=default_backend()
        )
        public_key = private_key.public_key()
        
        # 解码签名
        signature_bytes = base64.b64decode(wechatpay_signature)
        
        # 验证签名
        try:
            public_key.verify(
                signature_bytes,
                message.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            logger.info("[WeChatPayV3] 回调签名验证通过")
            return True
        except Exception:
            logger.warning("[WeChatPayV3] 回调签名验证失败")
            return False
            
    except Exception as e:
        logger.error(f"[WeChatPayV3] 回调签名验证异常: {e}")
        return False


async def create_v3_jsapi_order(
    openid: str,
    total_fee: int,
    description: str,
    out_trade_no: str,
    attach: str = "",
    time_expire: Optional[str] = None
) -> Dict[str, Any]:
    """
    微信支付V3 JSAPI下单（统一下单）
    
    Args:
        openid: 用户微信openid
        total_fee: 订单金额（单位：分）
        description: 商品描述
        out_trade_no: 商户订单号
        attach: 附加数据（回调时原样返回）
        time_expire: 订单过期时间（ISO 8601格式）
    
    Returns:
        包含prepay_id的响应字典
    
    Raises:
        ValueError: 参数错误或API调用失败
    """
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    
    if not WECHAT_PAY_V3_NOTIFY_URL:
        raise ValueError("WECHAT_PAY_V3_NOTIFY_URL 环境变量未设置")
    
    # 构建请求体
    request_body = {
        "appid": WECHAT_APPID,
        "mchid": WECHAT_PAY_V3_MCHID,
        "description": description,
        "out_trade_no": out_trade_no,
        "notify_url": WECHAT_PAY_V3_NOTIFY_URL,
        "amount": {
            "total": total_fee,
            "currency": "CNY"
        },
        "payer": {
            "openid": openid
        },
        "attach": attach if attach else None
    }
    
    # 可选：设置订单过期时间
    if time_expire:
        request_body["time_expire"] = time_expire
    
    # 过滤掉None值
    request_body = {k: v for k, v in request_body.items() if v is not None}
    
    url_path = "/v3/pay/transactions/jsapi"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    body_str = json.dumps(request_body, ensure_ascii=False)
    
    # 构建认证头
    headers = _build_v3_auth_header("POST", url_path, body_str)
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=headers, content=body_str)
                
                if response.status_code == 200 or response.status_code == 201:
                    result = response.json()
                    logger.info(f"[WeChatPayV3] JSAPI下单成功: out_trade_no={out_trade_no}")
                    return result
                else:
                    error_body = response.text
                    logger.error(f"[WeChatPayV3] JSAPI下单失败 (尝试 {attempt + 1}/{max_retries}): "
                                f"status={response.status_code}, body={error_body}")
                    
                    if attempt < max_retries - 1 and response.status_code >= 500:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    raise ValueError(f"JSAPI下单失败: status={response.status_code}, body={error_body}")
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatPayV3] JSAPI下单网络错误 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise ValueError(f"JSAPI下单网络错误: {e}")


def generate_v3_jsapi_pay_params(prepay_id: str) -> Dict[str, str]:
    """
    生成JSAPI调起支付所需的参数（供前端使用）
    
    Args:
        prepay_id: 统一下单返回的prepay_id
    
    Returns:
        包含appId、timeStamp、nonceStr、package、signType、paySign的字典
    """
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    
    # 生成随机字符串
    nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    timestamp = str(int(time.time()))
    
    # 构建package
    package = f"prepay_id={prepay_id}"
    
    # 构建待签名字符串
    message = f"{WECHAT_APPID}\n{timestamp}\n{nonce_str}\n{package}\n"
    
    # 生成签名
    pay_sign = _sign_v3_with_private_key(message)
    
    return {
        "appId": WECHAT_APPID,
        "timeStamp": timestamp,
        "nonceStr": nonce_str,
        "package": package,
        "signType": "RSA",
        "paySign": pay_sign
    }


async def query_v3_order_by_out_trade_no(out_trade_no: str) -> Dict[str, Any]:
    """
    微信支付V3订单查询（通过商户订单号）
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        订单信息字典
    
    Raises:
        ValueError: 查询失败
    """
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    
    url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}"
    params = f"?mchid={WECHAT_PAY_V3_MCHID}"
    full_url_path = f"{url_path}{params}"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{full_url_path}"
    
    # 构建认证头（GET请求body为空字符串）
    headers = _build_v3_auth_header("GET", full_url_path)
    headers["Accept"] = "application/json"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"[WeChatPayV3] 订单查询成功: out_trade_no={out_trade_no}")
                return result
            else:
                error_body = response.text
                logger.error(f"[WeChatPayV3] 订单查询失败: status={response.status_code}, body={error_body}")
                raise ValueError(f"订单查询失败: status={response.status_code}, body={error_body}")
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 订单查询网络错误: {e}")
        raise ValueError(f"订单查询网络错误: {e}")


async def query_v3_order_by_transaction_id(transaction_id: str) -> Dict[str, Any]:
    """
    微信支付V3订单查询（通过微信支付订单号）
    
    Args:
        transaction_id: 微信支付订单号
    
    Returns:
        订单信息字典
    
    Raises:
        ValueError: 查询失败
    """
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    
    url_path = f"/v3/pay/transactions/id/{transaction_id}"
    params = f"?mchid={WECHAT_PAY_V3_MCHID}"
    full_url_path = f"{url_path}{params}"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{full_url_path}"
    
    # 构建认证头（GET请求body为空字符串）
    headers = _build_v3_auth_header("GET", full_url_path)
    headers["Accept"] = "application/json"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"[WeChatPayV3] 订单查询成功: transaction_id={transaction_id}")
                return result
            else:
                error_body = response.text
                logger.error(f"[WeChatPayV3] 订单查询失败: status={response.status_code}, body={error_body}")
                raise ValueError(f"订单查询失败: status={response.status_code}, body={error_body}")
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 订单查询网络错误: {e}")
        raise ValueError(f"订单查询网络错误: {e}")


async def close_v3_order(out_trade_no: str) -> bool:
    """
    微信支付V3关闭订单
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        是否关闭成功
    
    Raises:
        ValueError: 关闭失败
    """
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    
    url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    request_body = {
        "mchid": WECHAT_PAY_V3_MCHID
    }
    body_str = json.dumps(request_body, ensure_ascii=False)
    
    # 构建认证头
    headers = _build_v3_auth_header("POST", url_path, body_str)
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, content=body_str)
            
            if response.status_code == 204:
                logger.info(f"[WeChatPayV3] 订单关闭成功: out_trade_no={out_trade_no}")
                return True
            else:
                error_body = response.text
                logger.error(f"[WeChatPayV3] 订单关闭失败: status={response.status_code}, body={error_body}")
                raise ValueError(f"订单关闭失败: status={response.status_code}, body={error_body}")
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 订单关闭网络错误: {e}")
        raise ValueError(f"订单关闭网络错误: {e}")


async def refund_v3_order(
    out_trade_no: str,
    refund_amount: int,
    total_amount: int,
    out_refund_no: str,
    reason: str = "",
    notify_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    微信支付V3申请退款
    
    Args:
        out_trade_no: 商户订单号
        refund_amount: 退款金额（单位：分）
        total_amount: 原订单金额（单位：分）
        out_refund_no: 商户退款单号
        reason: 退款原因
        notify_url: 退款结果回调地址
    
    Returns:
        退款响应字典
    
    Raises:
        ValueError: 退款申请失败
    """
    url_path = "/v3/refund/domestic/refunds"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    request_body = {
        "out_trade_no": out_trade_no,
        "out_refund_no": out_refund_no,
        "amount": {
            "refund": refund_amount,
            "total": total_amount,
            "currency": "CNY"
        },
        "reason": reason if reason else None,
        "notify_url": notify_url if notify_url else None
    }
    
    # 过滤掉None值
    request_body = {k: v for k, v in request_body.items() if v is not None}
    
    body_str = json.dumps(request_body, ensure_ascii=False)
    
    # 构建认证头
    headers = _build_v3_auth_header("POST", url_path, body_str)
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=headers, content=body_str)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"[WeChatPayV3] 退款申请成功: out_refund_no={out_refund_no}")
                    return result
                else:
                    error_body = response.text
                    logger.error(f"[WeChatPayV3] 退款申请失败 (尝试 {attempt + 1}/{max_retries}): "
                                f"status={response.status_code}, body={error_body}")
                    
                    if attempt < max_retries - 1 and response.status_code >= 500:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    raise ValueError(f"退款申请失败: status={response.status_code}, body={error_body}")
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatPayV3] 退款申请网络错误 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise ValueError(f"退款申请网络错误: {e}")


async def query_v3_refund(out_refund_no: str) -> Dict[str, Any]:
    """
    微信支付V3查询退款
    
    Args:
        out_refund_no: 商户退款单号
    
    Returns:
        退款信息字典
    
    Raises:
        ValueError: 查询失败
    """
    url_path = f"/v3/refund/domestic/refunds/{out_refund_no}"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    # 构建认证头（GET请求body为空字符串）
    headers = _build_v3_auth_header("GET", url_path)
    headers["Accept"] = "application/json"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"[WeChatPayV3] 退款查询成功: out_refund_no={out_refund_no}")
                return result
            else:
                error_body = response.text
                logger.error(f"[WeChatPayV3] 退款查询失败: status={response.status_code}, body={error_body}")
                raise ValueError(f"退款查询失败: status={response.status_code}, body={error_body}")
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 退款查询网络错误: {e}")
        raise ValueError(f"退款查询网络错误: {e}")


def parse_v3_payment_callback(body: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """
    解析微信支付V3支付结果回调通知
    
    Args:
        body: 回调请求体（原始JSON字符串）
        headers: 回调请求头
    
    Returns:
        解析后的回调数据字典（包含resource解密后的内容）
    
    Raises:
        ValueError: 签名验证失败或解密失败
    """
    # 验证签名
    if not _verify_v3_callback_signature(headers, body):
        raise ValueError("微信支付V3回调签名验证失败")
    
    # 解析请求体
    try:
        callback_data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"回调请求体JSON解析失败: {e}")
    
    # 获取加密资源
    resource = callback_data.get("resource", {})
    if not resource:
        raise ValueError("回调数据缺少resource字段")
    
    associated_data = resource.get("associated_data", "")
    nonce = resource.get("nonce", "")
    ciphertext = resource.get("ciphertext", "")
    
    if not all([nonce, ciphertext]):
        raise ValueError("回调数据resource字段不完整")
    
    # 解密资源
    plaintext = _decrypt_v3_callback_data(associated_data, nonce, ciphertext)
    
    try:
        payment_data = json.loads(plaintext)
    except json.JSONDecodeError as e:
        raise ValueError(f"解密后的数据JSON解析失败: {e}")
    
    logger.info(f"[WeChatPayV3] 支付回调解析成功: out_trade_no={payment_data.get('out_trade_no')}")
    
    return {
        "event_type": callback_data.get("event_type", ""),
        "summary": callback_data.get("summary", ""),
        "payment_data": payment_data
    }


def parse_v3_refund_callback(body: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """
    解析微信支付V3退款结果回调通知
    
    Args:
        body: 回调请求体（原始JSON字符串）
        headers: 回调请求头
    
    Returns:
        解析后的回调数据字典（包含resource解密后的内容）
    
    Raises:
        ValueError: 签名验证失败或解密失败
    """
    # 验证签名
    if not _verify_v3_callback_signature(headers, body):
        raise ValueError("微信支付V3退款回调签名验证失败")
    
    # 解析请求体
    try:
        callback_data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"回调请求体JSON解析失败: {e}")
    
    # 获取加密资源
    resource = callback_data.get("resource", {})
    if not resource:
        raise ValueError("回调数据缺少resource字段")
    
    associated_data = resource.get("associated_data", "")
    nonce = resource.get("nonce", "")
    ciphertext = resource.get("ciphertext", "")
    
    if not all([nonce, ciphertext]):
        raise ValueError("回调数据resource字段不完整")
    
    # 解密资源
    plaintext = _decrypt_v3_callback_data(associated_data, nonce, ciphertext)
    
    try:
        refund_data = json.loads(plaintext)
    except json.JSONDecodeError as e:
        raise ValueError(f"解密后的数据JSON解析失败: {e}")
    
    logger.info(f"[WeChatPayV3] 退款回调解析成功: out_refund_no={refund_data.get('out_refund_no')}")
    
    return {
        "event_type": callback_data.get("event_type", ""),
        "summary": callback_data.get("summary", ""),
        "refund_data": refund_data
    }


# ============================================================
# 微信支付V2兼容函数（保留原有接口）
# ============================================================

def _generate_v2_sign(params: Dict[str, str], sign_type: str = "MD5") -> str:
    """
    生成微信支付V2签名（MD5或HMAC-SHA256）
    
    Args:
        params: 参数字典（不包含sign字段）
        sign_type: 签名类型（MD5或HMAC-SHA256）
    
    Returns:
        签名字符串（大写）
    """
    if not WECHAT_MCHKEY:
        raise ValueError("WECHAT_MCHKEY 环境变量未设置")
    
    # 按字典序排序
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    
    # 拼接参数
    sign_str = "&".join([f"{k}={v}" for k, v in sorted_params if v != ""])
    sign_str += f"&key={WECHAT_MCHKEY}"
    
    if sign_type == "HMAC-SHA256":
        sign = hmac.new(
            WECHAT_MCHKEY.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256
        ).hexdigest().upper()
    else:
        sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()
    
    return sign


def _build_v2_xml(params: Dict[str, str]) -> str:
    """
    构建微信支付V2 XML请求体
    
    Args:
        params: 参数字典
    
    Returns:
        XML字符串
    """
    root = ET.Element("xml")
    for key, value in params.items():
        child = ET.SubElement(root, key)
        child.text = str(value)
    return ET.tostring(root, encoding="utf-8").decode("utf-8")


def _parse_v2_xml(xml_str: str) -> Dict[str, str]:
    """
    解析微信支付V2 XML响应
    
    Args:
        xml_str: XML字符串
    
    Returns:
        解析后的字典
    """
    try:
        root = ET.fromstring(xml_str)
        result = {}
        for child in root:
            result[child.tag] = child.text or ""
        return result
    except ET.ParseError as e:
        logger.error(f"[WeChatPayV2] XML解析失败: {e}")
        return {}


async def create_v2_jsapi_order(
    openid: str,
    total_fee: int,
    description: str,
    out_trade_no: str,
    attach: str = "",
    time_expire: Optional[str] = None
) -> Dict[str, Any]:
    """
    微信支付V2 JSAPI下单（统一下单）
    保留V2接口用于兼容
    
    Args:
        openid: 用户微信openid
        total_fee: 订单金额（单位：分）
        description: 商品描述
        out_trade_no: 商户订单号
        attach: 附加数据
        time_expire: 订单过期时间
    
    Returns:
        包含prepay_id的响应字典
    """
    if not WECHAT_APPID or not WECHAT_MCHID:
        raise ValueError("WECHAT_APPID 或 WECHAT_MCHID 环境变量未设置")
    
    if not WECHAT_NOTIFY_URL:
        raise ValueError("WECHAT_NOTIFY_URL 环境变量未设置")
    
    # 构建请求参数
    params = {
        "appid": WECHAT_APPID,
        "mch_id": WECHAT_MCHID,
        "nonce_str": ''.join(random.choices(string.ascii_letters + string.digits, k=32)),
        "body": description,
        "out_trade
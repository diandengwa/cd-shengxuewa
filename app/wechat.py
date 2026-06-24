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
            raise ValueError(f"获取access_token失败: {e}")


def _load_v3_private_key() -> bytes:
    """
    加载微信支付V3商户私钥
    
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
        
        # 验证私钥格式
        serialization.load_pem_private_key(
            private_key_data,
            password=None,
            backend=default_backend()
        )
        
        _v3_private_key_cache = private_key_data
        logger.info("[WeChatPayV3] 商户私钥加载成功")
        return private_key_data
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 加载商户私钥失败: {e}")
        raise ValueError(f"加载商户私钥失败: {e}")


def _get_v3_private_key_object():
    """
    获取V3私钥对象
    
    Returns:
        rsa.RSAPrivateKey对象
    """
    private_key_pem = _load_v3_private_key()
    return serialization.load_pem_private_key(
        private_key_pem,
        password=None,
        backend=default_backend()
    )


def generate_v3_sign(method: str, url_path: str, body: str = "", timestamp: str = None, nonce_str: str = None) -> str:
    """
    生成微信支付V3 API签名
    
    Args:
        method: HTTP方法（GET/POST/PUT/DELETE）
        url_path: 请求路径（如 /v3/pay/transactions/jsapi）
        body: 请求体字符串（GET请求为空字符串）
        timestamp: 时间戳（10位秒级），不传则自动生成
        nonce_str: 随机字符串，不传则自动生成
    
    Returns:
        签名结果字符串
    
    Raises:
        ValueError: 配置缺失或签名失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    if not WECHAT_PAY_V3_SERIAL_NO:
        raise ValueError("WECHAT_PAY_V3_SERIAL_NO 环境变量未设置")
    
    # 生成时间戳和随机字符串
    if timestamp is None:
        timestamp = str(int(time.time()))
    if nonce_str is None:
        nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # 构建签名串
    sign_str = f"{method}\n{url_path}\n{timestamp}\n{nonce_str}\n{body}\n"
    
    try:
        # 加载私钥并签名
        private_key = _get_v3_private_key_object()
        signature = private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        # Base64编码签名
        signature_b64 = base64.b64encode(signature).decode("utf-8")
        
        # 构建Authorization头
        authorization = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{WECHAT_PAY_V3_MCHID}",'
            f'nonce_str="{nonce_str}",'
            f'serial_no="{WECHAT_PAY_V3_SERIAL_NO}",'
            f'signature="{signature_b64}",'
            f'timestamp="{timestamp}"'
        )
        
        logger.debug(f"[WeChatPayV3] 签名生成成功, method={method}, url_path={url_path}")
        return authorization
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 签名生成失败: {e}")
        raise ValueError(f"签名生成失败: {e}")


def _get_v3_headers(method: str, url_path: str, body: str = "", accept: str = "application/json") -> Dict[str, str]:
    """
    获取微信支付V3 API请求头
    
    Args:
        method: HTTP方法
        url_path: 请求路径
        body: 请求体
        accept: Accept头
    
    Returns:
        请求头字典
    """
    authorization = generate_v3_sign(method, url_path, body)
    
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json",
        "Accept": accept,
        "User-Agent": "K12-Rocket/2.0"
    }
    
    return headers


def create_v3_jsapi_order(
    openid: str,
    total_fee: int,
    description: str,
    out_trade_no: str,
    attach: str = "",
    time_expire: Optional[str] = None,
    goods_tag: Optional[str] = None
) -> Dict[str, Any]:
    """
    微信支付V3 JSAPI下单
    
    Args:
        openid: 用户openid
        total_fee: 订单金额（单位：分）
        description: 商品描述
        out_trade_no: 商户订单号
        attach: 附加数据（回调时原样返回）
        time_expire: 订单过期时间（RFC 3339格式）
        goods_tag: 商品标记
    
    Returns:
        下单响应结果，包含prepay_id
    
    Raises:
        ValueError: 参数验证失败
        httpx.HTTPError: 请求失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    if not WECHAT_PAY_V3_NOTIFY_URL:
        raise ValueError("WECHAT_PAY_V3_NOTIFY_URL 环境变量未设置")
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    
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
        }
    }
    
    # 可选参数
    if attach:
        request_body["attach"] = attach
    if time_expire:
        request_body["time_expire"] = time_expire
    if goods_tag:
        request_body["goods_tag"] = goods_tag
    
    url_path = "/v3/pay/transactions/jsapi"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    body_str = json.dumps(request_body, ensure_ascii=False)
    
    headers = _get_v3_headers("POST", url_path, body_str)
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, headers=headers, content=body_str)
                response.raise_for_status()
                result = response.json()
                
                logger.info(f"[WeChatPayV3] JSAPI下单成功, out_trade_no={out_trade_no}, prepay_id={result.get('prepay_id', 'N/A')}")
                return result
                
        except httpx.HTTPStatusError as e:
            error_body = e.response.text if e.response else "无响应体"
            logger.error(f"[WeChatPayV3] JSAPI下单失败 (尝试 {attempt + 1}/{max_retries}): HTTP {e.response.status_code}, body={error_body}")
            
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            
            # 尝试解析错误信息
            try:
                error_data = json.loads(error_body)
                raise ValueError(f"JSAPI下单失败: {error_data.get('message', error_body)}")
            except json.JSONDecodeError:
                raise ValueError(f"JSAPI下单失败: HTTP {e.response.status_code}, {error_body}")
                
        except httpx.HTTPError as e:
            logger.error(f"[WeChatPayV3] JSAPI下单请求异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise ValueError(f"JSAPI下单请求异常: {e}")


def get_v3_order_by_out_trade_no(out_trade_no: str) -> Dict[str, Any]:
    """
    微信支付V3查询订单（通过商户订单号）
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        订单查询结果
    
    Raises:
        ValueError: 查询失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    
    url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={WECHAT_PAY_V3_MCHID}"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    headers = _get_v3_headers("GET", url_path)
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"[WeChatPayV3] 订单查询成功, out_trade_no={out_trade_no}, trade_state={result.get('trade_state', 'N/A')}")
            return result
            
    except httpx.HTTPStatusError as e:
        error_body = e.response.text if e.response else "无响应体"
        logger.error(f"[WeChatPayV3] 订单查询失败: HTTP {e.response.status_code}, body={error_body}")
        try:
            error_data = json.loads(error_body)
            raise ValueError(f"订单查询失败: {error_data.get('message', error_body)}")
        except json.JSONDecodeError:
            raise ValueError(f"订单查询失败: HTTP {e.response.status_code}, {error_body}")
            
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 订单查询请求异常: {e}")
        raise ValueError(f"订单查询请求异常: {e}")


def get_v3_order_by_transaction_id(transaction_id: str) -> Dict[str, Any]:
    """
    微信支付V3查询订单（通过微信支付订单号）
    
    Args:
        transaction_id: 微信支付订单号
    
    Returns:
        订单查询结果
    
    Raises:
        ValueError: 查询失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    
    url_path = f"/v3/pay/transactions/id/{transaction_id}?mchid={WECHAT_PAY_V3_MCHID}"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    headers = _get_v3_headers("GET", url_path)
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"[WeChatPayV3] 订单查询成功, transaction_id={transaction_id}, trade_state={result.get('trade_state', 'N/A')}")
            return result
            
    except httpx.HTTPStatusError as e:
        error_body = e.response.text if e.response else "无响应体"
        logger.error(f"[WeChatPayV3] 订单查询失败: HTTP {e.response.status_code}, body={error_body}")
        try:
            error_data = json.loads(error_body)
            raise ValueError(f"订单查询失败: {error_data.get('message', error_body)}")
        except json.JSONDecodeError:
            raise ValueError(f"订单查询失败: HTTP {e.response.status_code}, {error_body}")
            
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 订单查询请求异常: {e}")
        raise ValueError(f"订单查询请求异常: {e}")


def close_v3_order(out_trade_no: str) -> bool:
    """
    微信支付V3关闭订单
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        关闭成功返回True
    
    Raises:
        ValueError: 关闭失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    
    url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    request_body = {
        "mchid": WECHAT_PAY_V3_MCHID
    }
    body_str = json.dumps(request_body, ensure_ascii=False)
    
    headers = _get_v3_headers("POST", url_path, body_str)
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, headers=headers, content=body_str)
            
            # 关闭订单成功返回204 No Content
            if response.status_code == 204:
                logger.info(f"[WeChatPayV3] 订单关闭成功, out_trade_no={out_trade_no}")
                return True
            else:
                response.raise_for_status()
                return True
                
    except httpx.HTTPStatusError as e:
        error_body = e.response.text if e.response else "无响应体"
        logger.error(f"[WeChatPayV3] 订单关闭失败: HTTP {e.response.status_code}, body={error_body}")
        try:
            error_data = json.loads(error_body)
            raise ValueError(f"订单关闭失败: {error_data.get('message', error_body)}")
        except json.JSONDecodeError:
            raise ValueError(f"订单关闭失败: HTTP {e.response.status_code}, {error_body}")
            
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 订单关闭请求异常: {e}")
        raise ValueError(f"订单关闭请求异常: {e}")


def create_v3_refund(
    out_trade_no: str,
    refund_amount: int,
    total_amount: int,
    out_refund_no: str,
    reason: Optional[str] = None,
    refund_desc: Optional[str] = None,
    notify_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    微信支付V3申请退款
    
    Args:
        out_trade_no: 商户订单号（与transaction_id二选一）
        refund_amount: 退款金额（单位：分）
        total_amount: 原订单金额（单位：分）
        out_refund_no: 商户退款单号
        reason: 退款原因
        refund_desc: 退款描述
        notify_url: 退款结果回调地址
    
    Returns:
        退款申请结果
    
    Raises:
        ValueError: 退款申请失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    
    # 构建请求体
    request_body = {
        "out_trade_no": out_trade_no,
        "out_refund_no": out_refund_no,
        "amount": {
            "refund": refund_amount,
            "total": total_amount,
            "currency": "CNY"
        }
    }
    
    # 可选参数
    if reason:
        request_body["reason"] = reason
    if refund_desc:
        request_body["refund_desc"] = refund_desc
    if notify_url:
        request_body["notify_url"] = notify_url
    
    url_path = "/v3/refund/domestic/refunds"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    body_str = json.dumps(request_body, ensure_ascii=False)
    
    headers = _get_v3_headers("POST", url_path, body_str)
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, headers=headers, content=body_str)
                response.raise_for_status()
                result = response.json()
                
                logger.info(f"[WeChatPayV3] 退款申请成功, out_trade_no={out_trade_no}, out_refund_no={out_refund_no}, refund_id={result.get('refund_id', 'N/A')}")
                return result
                
        except httpx.HTTPStatusError as e:
            error_body = e.response.text if e.response else "无响应体"
            logger.error(f"[WeChatPayV3] 退款申请失败 (尝试 {attempt + 1}/{max_retries}): HTTP {e.response.status_code}, body={error_body}")
            
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            
            try:
                error_data = json.loads(error_body)
                raise ValueError(f"退款申请失败: {error_data.get('message', error_body)}")
            except json.JSONDecodeError:
                raise ValueError(f"退款申请失败: HTTP {e.response.status_code}, {error_body}")
                
        except httpx.HTTPError as e:
            logger.error(f"[WeChatPayV3] 退款申请请求异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise ValueError(f"退款申请请求异常: {e}")


def query_v3_refund(out_refund_no: str) -> Dict[str, Any]:
    """
    微信支付V3查询退款
    
    Args:
        out_refund_no: 商户退款单号
    
    Returns:
        退款查询结果
    
    Raises:
        ValueError: 查询失败
    """
    url_path = f"/v3/refund/domestic/refunds/{out_refund_no}"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    headers = _get_v3_headers("GET", url_path)
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"[WeChatPayV3] 退款查询成功, out_refund_no={out_refund_no}, status={result.get('status', 'N/A')}")
            return result
            
    except httpx.HTTPStatusError as e:
        error_body = e.response.text if e.response else "无响应体"
        logger.error(f"[WeChatPayV3] 退款查询失败: HTTP {e.response.status_code}, body={error_body}")
        try:
            error_data = json.loads(error_body)
            raise ValueError(f"退款查询失败: {error_data.get('message', error_body)}")
        except json.JSONDecodeError:
            raise ValueError(f"退款查询失败: HTTP {e.response.status_code}, {error_body}")
            
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 退款查询请求异常: {e}")
        raise ValueError(f"退款查询请求异常: {e}")


def verify_v3_signature(
    serial_no: str,
    signature: str,
    timestamp: str,
    nonce: str,
    body: str
) -> bool:
    """
    验证微信支付V3回调签名
    
    Args:
        serial_no: 微信平台证书序列号
        signature: 签名值（Base64编码）
        timestamp: 时间戳
        nonce: 随机字符串
        body: 请求体（原始字符串）
    
    Returns:
        签名验证通过返回True
    
    Raises:
        ValueError: 验证失败
    """
    # 构建待验签字符串
    sign_str = f"{timestamp}\n{nonce}\n{body}\n"
    
    try:
        # 获取微信平台证书（实际生产环境应缓存并定期更新）
        # 这里简化处理，需要从微信平台获取证书
        # 建议实现一个证书管理器来缓存和更新平台证书
        platform_cert = _get_platform_certificate(serial_no)
        if not platform_cert:
            logger.error(f"[WeChatPayV3] 未找到序列号为 {serial_no} 的平台证书")
            return False
        
        # 验证签名
        signature_bytes = base64.b64decode(signature)
        platform_cert.verify(
            signature_bytes,
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        logger.debug("[WeChatPayV3] 回调签名验证通过")
        return True
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 回调签名验证失败: {e}")
        return False


def _get_platform_certificate(serial_no: str):
    """
    获取微信平台证书（简化实现）
    
    注意：生产环境应实现证书缓存和自动更新机制
    
    Args:
        serial_no: 证书序列号
    
    Returns:
        公钥对象或None
    """
    # 实际实现中，应调用 https://api.mch.weixin.qq.com/v3/certificates 获取平台证书
    # 并缓存证书列表，定期更新
    # 这里返回None表示需要实际实现证书获取逻辑
    logger.warning("[WeChatPayV3] 平台证书获取未实现，请实现证书管理器")
    return None


def decrypt_v3_callback_data(associated_data: str, nonce: str, ciphertext: str) -> Dict[str, Any]:
    """
    解密微信支付V3回调通知中的加密数据
    
    Args:
        associated_data: 附加数据
        nonce: 随机串
        ciphertext: 密文（Base64编码）
    
    Returns:
        解密后的JSON数据
    
    Raises:
        ValueError: 解密失败
    """
    if not WECHAT_PAY_V3_API_V3_KEY:
        raise ValueError("WECHAT_PAY_V3_API_V3_KEY 环境变量未设置")
    
    try:
        # Base64解码密文
        ciphertext_bytes = base64.b64decode(ciphertext)
        
        # 使用APIv3密钥解密（AES-256-GCM）
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        
        # 提取认证标签（最后16字节）
        tag = ciphertext_bytes[-16:]
        encrypted_data = ciphertext_bytes[:-16]
        
        # 构建解密器
        cipher = Cipher(
            algorithms.AES(WECHAT_PAY_V3_API_V3_KEY.encode("utf-8")),
            modes.GCM(nonce.encode("utf-8"), tag),
            backend=default_backend()
        )
        
        decryptor = cipher.decryptor()
        
        # 关联数据验证
        decryptor.authenticate_additional_data(associated_data.encode("utf-8"))
        
        # 解密
        decrypted_data = decryptor.update(encrypted_data) + decryptor.finalize()
        
        # 解析JSON
        result = json.loads(decrypted_data.decode("utf-8"))
        
        logger.info("[WeChatPayV3] 回调数据解密成功")
        return result
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 回调数据解密失败: {e}")
        raise ValueError(f"回调数据解密失败: {e}")


def parse_v3_callback_notification(request_body: str, request_headers: Dict[str, str]) -> Dict[str, Any]:
    """
    解析微信支付V3回调通知
    
    Args:
        request_body: 请求体字符串
        request_headers: 请求头字典（需包含Wechatpay-Serial、Wechatpay-Signature等）
    
    Returns:
        解析后的通知数据
    
    Raises:
        ValueError: 解析失败或签名验证失败
    """
    # 获取必要的请求头
    wechatpay_serial = request_headers.get("Wechatpay-Serial", "")
    wechatpay_signature = request_headers.get("Wechatpay-Signature", "")
    wechatpay_timestamp = request_headers.get("Wechatpay-Timestamp", "")
    wechatpay_nonce = request_headers.get("Wechatpay-Nonce", "")
    
    # 验证必要参数
    if not all([wechatpay_serial, wechatpay_signature, wechatpay_timestamp, wechatpay_nonce]):
        raise ValueError("回调请求头缺少必要的验签参数")
    
    # 验证签名
    if not verify_v3_signature(
        wechatpay_serial,
        wechatpay_signature,
        wechatpay_timestamp,
        wechatpay_nonce,
        request_body
    ):
        raise ValueError("回调签名验证失败")
    
    # 解析请求体
    try:
        notification = json.loads(request_body)
    except json.JSONDecodeError as e:
        raise ValueError(f"回调请求体JSON解析失败: {e}")
    
    # 获取加密数据
    resource = notification.get("resource", {})
    associated_data = resource.get("associated_data", "")
    nonce = resource.get("nonce", "")
    ciphertext = resource.get("ciphertext", "")
    
    if not all([nonce, ciphertext]):
        raise ValueError("回调通知缺少加密数据")
    
    # 解密数据
    decrypted_data = decrypt_v3_callback_data(associated_data, nonce, ciphertext)
    
    return {
        "notification": notification,
        "decrypted_data": decrypted_data
    }


def generate_jsapi_package(prepay_id: str) -> Dict[str, str]:
    """
    生成JSAPI调起支付所需的参数包
    
    Args:
        prepay_id: 预支付交易会话ID
    
    Returns:
        JSAPI调起支付参数包
    
    Raises:
        ValueError: 配置缺失
    """
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    
    # 生成时间戳和随机字符串
    timestamp = str(int(time.time()))
    nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # 构建签名串
    package_str = f"prepay_id={prepay_id}"
    sign_str = f"{WECHAT_APPID}\n{timestamp}\n{nonce_str}\n{package_str}\n"
    
    try:
        # 使用商户私钥签名
        private_key = _get_v3_private_key_object()
        signature = private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        pay_sign = base64.b64encode(signature).decode("utf-8")
        
        # 构建返回参数
        params = {
            "appId": WECHAT_APPID,
            "timeStamp": timestamp,
            "nonceStr": nonce_str,
            "package": package_str,
            "signType": "RSA",
            "paySign": pay_sign
        }
        
        logger.info("[WeChatPayV3] JSAPI调起支付参数生成成功")
        return params
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] JSAPI调起支付参数生成失败: {e}")
        raise ValueError(f"JSAPI调起支付参数生成失败: {e}")


def generate_app_package(prepay_id: str) -> Dict[str, str]:
    """
    生成APP调起支付所需的参数包
    
    Args:
        prepay_id: 预支付交易会话ID
    
    Returns:
        APP调起支付参数包
    
    Raises:
        ValueError: 配置缺失
    """
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    
    # 生成时间戳和随机字符串
    timestamp = str(int(time.time()))
    nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # 构建签名串
    sign_str = f"{WECHAT_APPID}\n{timestamp}\n{nonce_str}\n{prepay_id}\n"
    
    try:
        # 使用商户私钥签名
        private_key = _get_v3_private_key_object()
        signature = private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        pay_sign = base64.b64encode(signature).decode("utf-8")
        
        # 构建返回参数
        params = {
            "appid": WECHAT_APPID,
            "partnerid": WECHAT_PAY_V3_MCHID,
            "prepayid": prepay_id,
            "package": "Sign=WXPay",
            "noncestr": nonce_str,

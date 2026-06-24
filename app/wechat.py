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


# ============================================================
# 微信支付V3 核心工具函数
# ============================================================

def load_v3_private_key() -> rsa.RSAPrivateKey:
    """
    加载微信支付V3商户私钥
    
    Returns:
        RSA私钥对象
    
    Raises:
        FileNotFoundError: 私钥文件不存在
        ValueError: 私钥加载失败
    """
    global _v3_private_key_cache
    
    if _v3_private_key_cache is not None:
        return _v3_private_key_cache
    
    if not WECHAT_PAY_V3_PRIVATE_KEY_PATH:
        raise ValueError("WECHAT_PAY_V3_PRIVATE_KEY_PATH 环境变量未设置")
    
    try:
        with open(WECHAT_PAY_V3_PRIVATE_KEY_PATH, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
        _v3_private_key_cache = private_key
        logger.info("[WeChatPayV3] 商户私钥加载成功")
        return private_key
    except FileNotFoundError:
        logger.error(f"[WeChatPayV3] 私钥文件不存在: {WECHAT_PAY_V3_PRIVATE_KEY_PATH}")
        raise
    except Exception as e:
        logger.error(f"[WeChatPayV3] 私钥加载失败: {e}")
        raise ValueError(f"私钥加载失败: {e}")


def generate_v3_sign(method: str, url_path: str, body: str = "", timestamp: str = None, nonce: str = None) -> str:
    """
    生成微信支付V3 API请求签名
    
    Args:
        method: HTTP方法（GET/POST/PUT/DELETE）
        url_path: 请求路径（如 /v3/pay/transactions/jsapi）
        body: 请求体字符串（GET请求为空字符串）
        timestamp: 时间戳（可选，自动生成）
        nonce: 随机字符串（可选，自动生成）
    
    Returns:
        签名字符串
    
    Raises:
        ValueError: 配置缺失或签名生成失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    if not WECHAT_PAY_V3_SERIAL_NO:
        raise ValueError("WECHAT_PAY_V3_SERIAL_NO 环境变量未设置")
    
    # 生成时间戳和随机字符串
    if timestamp is None:
        timestamp = str(int(time.time()))
    if nonce is None:
        nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # 构建签名串
    sign_str = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
    
    try:
        private_key = load_v3_private_key()
        # 使用SHA256-RSA签名
        signature = private_key.sign(
            sign_str.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        signature_b64 = base64.b64encode(signature).decode('utf-8')
        
        # 构建Authorization头
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{WECHAT_PAY_V3_MCHID}",'
            f'nonce_str="{nonce}",'
            f'signature="{signature_b64}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{WECHAT_PAY_V3_SERIAL_NO}"'
        )
        
        logger.debug(f"[WeChatPayV3] 签名生成成功, method={method}, path={url_path}")
        return auth_header
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 签名生成失败: {e}")
        raise ValueError(f"签名生成失败: {e}")


def verify_v3_callback_signature(timestamp: str, nonce: str, body: str, signature: str, serial_no: str) -> bool:
    """
    验证微信支付V3回调通知签名
    
    Args:
        timestamp: 回调中的时间戳
        nonce: 回调中的随机字符串
        body: 回调请求体（原始JSON字符串）
        signature: 回调中的签名
        serial_no: 回调中的证书序列号
    
    Returns:
        验证是否通过
    
    Raises:
        ValueError: 配置缺失
    """
    if not WECHAT_PAY_V3_API_V3_KEY:
        raise ValueError("WECHAT_PAY_V3_API_V3_KEY 环境变量未设置")
    
    try:
        # 构建待签名字符串
        sign_str = f"{timestamp}\n{nonce}\n{body}\n"
        
        # 使用APIv3密钥进行HMAC-SHA256验证
        expected_signature = hmac.new(
            WECHAT_PAY_V3_API_V3_KEY.encode('utf-8'),
            sign_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # 比较签名（微信返回的是小写hex）
        result = expected_signature == signature.lower()
        logger.info(f"[WeChatPayV3] 回调签名验证{'成功' if result else '失败'}")
        return result
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 回调签名验证异常: {e}")
        return False


def decrypt_v3_callback_data(associated_data: str, nonce: str, ciphertext: str) -> Dict[str, Any]:
    """
    解密微信支付V3回调通知中的敏感数据（AEAD_AES_256_GCM）
    
    Args:
        associated_data: 附加数据
        nonce: 随机串
        ciphertext: 密文（Base64编码）
    
    Returns:
        解密后的JSON对象
    
    Raises:
        ValueError: 解密失败
    """
    if not WECHAT_PAY_V3_API_V3_KEY:
        raise ValueError("WECHAT_PAY_V3_API_V3_KEY 环境变量未设置")
    
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        
        # 将APIv3密钥转换为字节
        api_key = WECHAT_PAY_V3_API_V3_KEY.encode('utf-8')
        
        # 解码密文
        ciphertext_bytes = base64.b64decode(ciphertext)
        
        # 构建AES-GCM解密参数
        aesgcm = AESGCM(api_key)
        
        # 解密（nonce需要是字节）
        nonce_bytes = nonce.encode('utf-8')
        associated_data_bytes = associated_data.encode('utf-8')
        
        plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, associated_data_bytes)
        
        # 解析JSON
        result = json.loads(plaintext.decode('utf-8'))
        logger.info("[WeChatPayV3] 回调数据解密成功")
        return result
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 回调数据解密失败: {e}")
        raise ValueError(f"回调数据解密失败: {e}")


# ============================================================
# 微信支付V3 统一下单接口
# ============================================================

async def create_v3_payment_order(
    openid: str,
    amount: int,
    description: str,
    out_trade_no: str,
    attach: str = "",
    goods_tag: str = "",
    time_expire: Optional[str] = None
) -> Dict[str, Any]:
    """
    微信支付V3 JSAPI统一下单
    
    Args:
        openid: 用户openid
        amount: 订单金额（分）
        description: 商品描述
        out_trade_no: 商户订单号
        attach: 附加数据（可选）
        goods_tag: 商品标记（可选）
        time_expire: 订单过期时间（RFC3339格式，可选）
    
    Returns:
        下单结果，包含prepay_id等
    
    Raises:
        ValueError: 参数错误或配置缺失
        httpx.HTTPError: 请求失败
    """
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
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
            "total": amount,
            "currency": "CNY"
        },
        "payer": {
            "openid": openid
        }
    }
    
    # 可选参数
    if attach:
        request_body["attach"] = attach
    if goods_tag:
        request_body["goods_tag"] = goods_tag
    if time_expire:
        request_body["time_expire"] = time_expire
    
    # 生成签名
    url_path = "/v3/pay/transactions/jsapi"
    body_str = json.dumps(request_body, ensure_ascii=False)
    auth_header = generate_v3_sign("POST", url_path, body_str)
    
    # 发送请求
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    content=body_str,
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": "k12-rocket/2.0"
                    }
                )
                
                if response.status_code == 200 or response.status_code == 201:
                    result = response.json()
                    logger.info(f"[WeChatPayV3] 统一下单成功, out_trade_no={out_trade_no}, prepay_id={result.get('prepay_id')}")
                    return result
                else:
                    error_body = response.text
                    logger.error(f"[WeChatPayV3] 统一下单失败 (尝试 {attempt + 1}/{max_retries}), status={response.status_code}, body={error_body}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    raise ValueError(f"统一下单失败: status={response.status_code}, body={error_body}")
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatPayV3] 统一下单请求异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise


def generate_v3_payment_params(prepay_id: str) -> Dict[str, str]:
    """
    生成JSAPI调起支付所需的参数
    
    Args:
        prepay_id: 预支付交易会话ID
    
    Returns:
        包含appId、timeStamp、nonceStr、package、signType、paySign的字典
    
    Raises:
        ValueError: 配置缺失
    """
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    
    # 生成时间戳和随机字符串
    timestamp = str(int(time.time()))
    nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # 构建package
    package = f"prepay_id={prepay_id}"
    
    # 构建签名串
    sign_str = f"{WECHAT_APPID}\n{timestamp}\n{nonce_str}\n{package}\n"
    
    try:
        private_key = load_v3_private_key()
        # 使用SHA256-RSA签名
        signature = private_key.sign(
            sign_str.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        pay_sign = base64.b64encode(signature).decode('utf-8')
        
        params = {
            "appId": WECHAT_APPID,
            "timeStamp": timestamp,
            "nonceStr": nonce_str,
            "package": package,
            "signType": "RSA",
            "paySign": pay_sign
        }
        
        logger.info("[WeChatPayV3] JSAPI支付参数生成成功")
        return params
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] JSAPI支付参数生成失败: {e}")
        raise ValueError(f"JSAPI支付参数生成失败: {e}")


# ============================================================
# 微信支付V3 订单查询接口
# ============================================================

async def query_v3_payment_order(out_trade_no: str) -> Dict[str, Any]:
    """
    查询微信支付V3订单状态（通过商户订单号）
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        订单信息
    
    Raises:
        ValueError: 配置缺失或查询失败
        httpx.HTTPError: 请求失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    
    # 构建URL路径（需要URL编码商户订单号）
    encoded_out_trade_no = quote(out_trade_no, safe='')
    url_path = f"/v3/pay/transactions/out-trade-no/{encoded_out_trade_no}?mchid={WECHAT_PAY_V3_MCHID}"
    
    # 生成签名
    auth_header = generate_v3_sign("GET", url_path)
    
    # 发送请求
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": auth_header,
                        "Accept": "application/json",
                        "User-Agent": "k12-rocket/2.0"
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"[WeChatPayV3] 订单查询成功, out_trade_no={out_trade_no}, trade_state={result.get('trade_state')}")
                    return result
                else:
                    error_body = response.text
                    logger.error(f"[WeChatPayV3] 订单查询失败 (尝试 {attempt + 1}/{max_retries}), status={response.status_code}, body={error_body}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    raise ValueError(f"订单查询失败: status={response.status_code}, body={error_body}")
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatPayV3] 订单查询请求异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise


async def query_v3_payment_order_by_transaction_id(transaction_id: str) -> Dict[str, Any]:
    """
    查询微信支付V3订单状态（通过微信支付订单号）
    
    Args:
        transaction_id: 微信支付订单号
    
    Returns:
        订单信息
    
    Raises:
        ValueError: 配置缺失或查询失败
        httpx.HTTPError: 请求失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    if not WECHAT_APPID:
        raise ValueError("WECHAT_APPID 环境变量未设置")
    
    # 构建URL路径
    url_path = f"/v3/pay/transactions/id/{transaction_id}?mchid={WECHAT_PAY_V3_MCHID}"
    
    # 生成签名
    auth_header = generate_v3_sign("GET", url_path)
    
    # 发送请求
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": auth_header,
                        "Accept": "application/json",
                        "User-Agent": "k12-rocket/2.0"
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"[WeChatPayV3] 订单查询成功, transaction_id={transaction_id}, trade_state={result.get('trade_state')}")
                    return result
                else:
                    error_body = response.text
                    logger.error(f"[WeChatPayV3] 订单查询失败 (尝试 {attempt + 1}/{max_retries}), status={response.status_code}, body={error_body}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    raise ValueError(f"订单查询失败: status={response.status_code}, body={error_body}")
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatPayV3] 订单查询请求异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise


# ============================================================
# 微信支付V3 退款接口
# ============================================================

async def create_v3_refund(
    out_refund_no: str,
    amount: int,
    transaction_id: Optional[str] = None,
    out_trade_no: Optional[str] = None,
    refund_reason: str = "",
    notify_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    微信支付V3申请退款
    
    Args:
        out_refund_no: 商户退款单号
        amount: 退款金额（分）
        transaction_id: 微信支付订单号（与out_trade_no二选一）
        out_trade_no: 商户订单号（与transaction_id二选一）
        refund_reason: 退款原因（可选）
        notify_url: 退款结果回调地址（可选）
    
    Returns:
        退款结果
    
    Raises:
        ValueError: 参数错误或配置缺失
        httpx.HTTPError: 请求失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    
    if not transaction_id and not out_trade_no:
        raise ValueError("transaction_id 和 out_trade_no 必须提供一个")
    
    # 构建请求体
    request_body = {
        "out_refund_no": out_refund_no,
        "amount": {
            "refund": amount,
            "total": amount,
            "currency": "CNY"
        }
    }
    
    if transaction_id:
        request_body["transaction_id"] = transaction_id
    else:
        request_body["out_trade_no"] = out_trade_no
    
    if refund_reason:
        request_body["reason"] = refund_reason
    
    if notify_url:
        request_body["notify_url"] = notify_url
    
    # 生成签名
    url_path = "/v3/refund/domestic/refunds"
    body_str = json.dumps(request_body, ensure_ascii=False)
    auth_header = generate_v3_sign("POST", url_path, body_str)
    
    # 发送请求
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    content=body_str,
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": "k12-rocket/2.0"
                    }
                )
                
                if response.status_code == 200 or response.status_code == 201:
                    result = response.json()
                    logger.info(f"[WeChatPayV3] 退款申请成功, out_refund_no={out_refund_no}, refund_id={result.get('refund_id')}")
                    return result
                else:
                    error_body = response.text
                    logger.error(f"[WeChatPayV3] 退款申请失败 (尝试 {attempt + 1}/{max_retries}), status={response.status_code}, body={error_body}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    raise ValueError(f"退款申请失败: status={response.status_code}, body={error_body}")
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatPayV3] 退款申请请求异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise


async def query_v3_refund(out_refund_no: str) -> Dict[str, Any]:
    """
    查询微信支付V3退款状态
    
    Args:
        out_refund_no: 商户退款单号
    
    Returns:
        退款信息
    
    Raises:
        ValueError: 配置缺失或查询失败
        httpx.HTTPError: 请求失败
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    
    # 构建URL路径
    encoded_out_refund_no = quote(out_refund_no, safe='')
    url_path = f"/v3/refund/domestic/refunds/{encoded_out_refund_no}"
    
    # 生成签名
    auth_header = generate_v3_sign("GET", url_path)
    
    # 发送请求
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": auth_header,
                        "Accept": "application/json",
                        "User-Agent": "k12-rocket/2.0"
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"[WeChatPayV3] 退款查询成功, out_refund_no={out_refund_no}, refund_status={result.get('status')}")
                    return result
                else:
                    error_body = response.text
                    logger.error(f"[WeChatPayV3] 退款查询失败 (尝试 {attempt + 1}/{max_retries}), status={response.status_code}, body={error_body}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    raise ValueError(f"退款查询失败: status={response.status_code}, body={error_body}")
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatPayV3] 退款查询请求异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise


# ============================================================
# 微信支付V3 回调处理
# ============================================================

def parse_v3_callback_notification(request_body: str, request_headers: Dict[str, str]) -> Dict[str, Any]:
    """
    解析微信支付V3回调通知
    
    Args:
        request_body: 请求体（原始JSON字符串）
        request_headers: 请求头字典（需包含Wechatpay-Signature等字段）
    
    Returns:
        解密后的回调数据
    
    Raises:
        ValueError: 验签失败或数据解析失败
    """
    # 获取回调头中的签名信息
    wechatpay_signature = request_headers.get("Wechatpay-Signature", "")
    wechatpay_timestamp = request_headers.get("Wechatpay-Timestamp", "")
    wechatpay_nonce = request_headers.get("Wechatpay-Nonce", "")
    wechatpay_serial = request_headers.get("Wechatpay-Serial", "")
    
    if not all([wechatpay_signature, wechatpay_timestamp, wechatpay_nonce, wechatpay_serial]):
        raise ValueError("回调请求头缺少必要的签名信息")
    
    # 验证签名
    if not verify_v3_callback_signature(
        wechatpay_timestamp,
        wechatpay_nonce,
        request_body,
        wechatpay_signature,
        wechatpay_serial
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
    
    if not all([associated_data, nonce, ciphertext]):
        raise ValueError("回调数据缺少加密信息")
    
    # 解密数据
    try:
        decrypted_data = decrypt_v3_callback_data(associated_data, nonce, ciphertext)
        return decrypted_data
    except Exception as e:
        raise ValueError(f"回调数据解密失败: {e}")


def generate_v3_callback_success_response() -> str:
    """
    生成微信支付V3回调成功响应
    
    Returns:
        JSON响应字符串
    """
    response = {
        "code": "SUCCESS",
        "message": "成功"
    }
    return json.dumps(response, ensure_ascii=False)


def generate_v3_callback_fail_response(message: str = "失败") -> str:
    """
    生成微信支付V3回调失败响应
    
    Args:
        message: 失败原因
    
    Returns:
        JSON响应字符串
    """
    response = {
        "code": "FAIL",
        "message": message
    }
    return json.dumps(response, ensure_ascii=False)


# ============================================================
# 微信支付V2 兼容接口（保留原有功能）
# ============================================================

def generate_pay_sign(params: Dict[str, str]) -> str:
    """
    生成微信支付V2签名（MD5）
    
    Args:
        params: 参数字典
    
    Returns:
        签名字符串
    """
    if not WECHAT_MCHKEY:
        raise ValueError("WECHAT_MCHKEY 环境变量未设置")
    
    # 按key排序
    sorted_keys = sorted(params.keys())
    sign_str = "&".join([f"{k}={params[k]}" for k in sorted_keys if params[k] and k != "sign"])
    sign_str += f"&key={WECHAT_MCHKEY}"
    
    # MD5签名
    sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
    return sign


def verify_pay_callback(xml_data: str) -> Dict[str, str]:
    """
    验证微信支付V2回调签名
    
    Args:
        xml_data: XML格式的回调数据
    
    Returns:
        解析后的参数字典
    
    Raises:
        ValueError: 验签失败
    """
    # 解析XML
    root = ET.fromstring(xml_data)
    params = {}
    for child in root:
        params[child.tag] = child.text
    
    # 验证签名
    if "sign" not in params:
        raise ValueError("回调数据缺少sign字段")
    
    expected_sign = params.pop("sign")
    actual_sign = generate_pay_sign(params)
    
    if expected_sign != actual_sign:
        raise ValueError(f"回调签名验证失败: expected={expected_sign}, actual={actual_sign}")
    
    return params


def generate_pay_callback_success_xml() -> str:
    """
    生成微信支付V2回调成功响应XML
    
    Returns:
        XML字符串
    """
    return """<xml>
  <return_code><![CDATA[SUCCESS]]></return_code>
  <return_msg><![CDATA[OK]]></return_msg>
</xml>"""


def generate_pay_callback_fail_xml(message: str = "签名失败") -> str:
    """
    生成微信支付V2回调失败响应XML
    
    Args:
        message: 失败原因
    
    Returns:
        XML字符串
    """
    return f"""<xml>
  <return_code><![CDATA[FAIL]]></return_code>
  <return_msg><![CDATA[{message}]]></return_msg>
</xml>"""


# ============================================================
# 工具函数：生成商户订单号
# ============================================================

def generate_out_trade_no(prefix: str =
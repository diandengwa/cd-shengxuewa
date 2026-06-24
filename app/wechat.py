```python
"""
微信草稿箱上传模块 — 内容工厂流水线
md排版 + 微信公众号草稿箱自动上传
支付相关工具函数（签名生成、回调解析）
扩展：微信支付V3配置和签名工具函数
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
from datetime import datetime
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
    
    raise ValueError("获取access_token失败，已达最大重试次数")


def get_permanent_access_token() -> str:
    """
    获取稳定的access_token（用于草稿箱API）
    与get_access_token区分，草稿箱API需使用稳定access_token
    
    稳定access_token的有效期更长，且不会频繁刷新，
    适合用于草稿箱上传等需要长时间稳定连接的操作。
    
    Returns:
        稳定access_token字符串
    
    Raises:
        ValueError: 获取失败时抛出
    """
    global _stable_access_token_cache
    
    # 检查缓存是否有效（提前10分钟过期，稳定token有效期更长）
    current_time = time.time()
    if _stable_access_token_cache["token"] and current_time < _stable_access_token_cache["expires_at"] - 600:
        return _stable_access_token_cache["token"]
    
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
                    _stable_access_token_cache["token"] = data["access_token"]
                    _stable_access_token_cache["expires_at"] = current_time + data.get("expires_in", 7200)
                    logger.info("[WeChatDraft] 稳定access_token获取成功")
                    return data["access_token"]
                else:
                    error_msg = f"获取稳定access_token失败: {data.get('errmsg', '未知错误')}"
                    logger.error(f"[WeChatDraft] {error_msg}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    raise ValueError(error_msg)
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatDraft] 请求稳定access_token失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise ValueError(f"获取稳定access_token网络错误: {e}")
    
    raise ValueError("获取稳定access_token失败，已达最大重试次数")


# ============================================================
# 微信支付V2工具函数（兼容旧版）
# ============================================================

def generate_pay_sign_v2(params: Dict[str, str]) -> str:
    """
    生成微信支付V2签名（MD5）
    
    按照微信支付V2签名规则：
    1. 参数名ASCII码从小到大排序（字典序）
    2. 使用URL键值对的格式拼接成字符串
    3. 在最后拼接上key=API密钥
    4. MD5加密后转大写
    
    Args:
        params: 待签名的参数字典（不包含sign字段）
    
    Returns:
        签名结果字符串（大写）
    """
    if not WECHAT_MCHKEY:
        raise ValueError("WECHAT_MCHKEY 环境变量未设置")
    
    # 过滤空值参数，排除sign字段
    filtered_params = {k: v for k, v in params.items() if v and k != "sign"}
    
    # 按字典序排序
    sorted_keys = sorted(filtered_params.keys())
    
    # 拼接字符串
    sign_str = "&".join([f"{k}={filtered_params[k]}" for k in sorted_keys])
    sign_str += f"&key={WECHAT_MCHKEY}"
    
    # MD5加密
    sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()
    
    logger.debug(f"[WeChatPayV2] 签名原始字符串: {sign_str}")
    logger.debug(f"[WeChatPayV2] 生成签名: {sign}")
    
    return sign


def verify_pay_sign_v2(params: Dict[str, str]) -> bool:
    """
    验证微信支付V2回调签名
    
    Args:
        params: 回调参数（包含sign字段）
    
    Returns:
        签名是否有效
    """
    if "sign" not in params:
        logger.warning("[WeChatPayV2] 回调参数中缺少sign字段")
        return False
    
    expected_sign = params["sign"]
    calculated_sign = generate_pay_sign_v2(params)
    
    return expected_sign == calculated_sign


def parse_pay_notification_v2(xml_data: str) -> Dict[str, str]:
    """
    解析微信支付V2回调通知XML
    
    Args:
        xml_data: XML格式的通知数据
    
    Returns:
        解析后的参数字典
    """
    try:
        root = ET.fromstring(xml_data)
        result = {}
        for child in root:
            result[child.tag] = child.text or ""
        return result
    except ET.ParseError as e:
        logger.error(f"[WeChatPayV2] XML解析失败: {e}")
        return {}


def build_success_response_v2() -> str:
    """
    构建微信支付V2回调成功响应XML
    
    Returns:
        成功响应的XML字符串
    """
    return """<xml>
  <return_code><![CDATA[SUCCESS]]></return_code>
  <return_msg><![CDATA[OK]]></return_msg>
</xml>"""


def build_fail_response_v2(msg: str = "FAIL") -> str:
    """
    构建微信支付V2回调失败响应XML
    
    Args:
        msg: 失败原因
    
    Returns:
        失败响应的XML字符串
    """
    return f"""<xml>
  <return_code><![CDATA[FAIL]]></return_code>
  <return_msg><![CDATA[{msg}]]></return_msg>
</xml>"""


# ============================================================
# 微信支付V3工具函数
# ============================================================

def _load_v3_private_key() -> Optional[rsa.RSAPrivateKey]:
    """
    加载微信支付V3商户私钥
    
    从文件路径加载商户私钥，用于生成请求签名
    
    Returns:
        RSA私钥对象，加载失败返回None
    """
    global _v3_private_key_cache
    
    if _v3_private_key_cache is not None:
        return _v3_private_key_cache
    
    if not WECHAT_PAY_V3_PRIVATE_KEY_PATH:
        logger.error("[WeChatPayV3] 商户私钥文件路径未设置")
        return None
    
    try:
        with open(WECHAT_PAY_V3_PRIVATE_KEY_PATH, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
        if not isinstance(private_key, rsa.RSAPrivateKey):
            logger.error("[WeChatPayV3] 加载的私钥不是RSA私钥")
            return None
        _v3_private_key_cache = private_key
        logger.info("[WeChatPayV3] 商户私钥加载成功")
        return private_key
    except Exception as e:
        logger.error(f"[WeChatPayV3] 加载商户私钥失败: {e}")
        return None


def generate_v3_sign(method: str, url: str, body: str = "", nonce_str: Optional[str] = None) -> Dict[str, str]:
    """
    生成微信支付V3 API请求签名
    
    按照微信支付V3签名规则：
    1. 构造签名串：HTTP请求方法 + \\n + URL + \\n + 时间戳 + \\n + 随机串 + \\n + 请求体 + \\n
    2. 使用商户私钥对签名串进行SHA256withRSA签名
    3. 构造Authorization头
    
    Args:
        method: HTTP方法（GET/POST/PUT等）
        url: 请求URL（不包含域名，如 /v3/pay/transactions/jsapi）
        body: 请求体字符串（GET请求为空字符串）
        nonce_str: 随机字符串，不传则自动生成
    
    Returns:
        包含Authorization头信息的字典，格式为：
        {
            "Authorization": "WECHATPAY2-SHA256-RSA2048 ...",
            "User-Agent": "..."
        }
    
    Raises:
        ValueError: 配置缺失或签名失败时抛出
    """
    if not WECHAT_PAY_V3_MCHID:
        raise ValueError("WECHAT_PAY_V3_MCHID 环境变量未设置")
    if not WECHAT_PAY_V3_SERIAL_NO:
        raise ValueError("WECHAT_PAY_V3_SERIAL_NO 环境变量未设置")
    
    private_key = _load_v3_private_key()
    if private_key is None:
        raise ValueError("无法加载商户私钥，请检查WECHAT_PAY_V3_PRIVATE_KEY_PATH配置")
    
    # 生成时间戳和随机串
    timestamp = str(int(time.time()))
    nonce_str = nonce_str or ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # 构造签名串
    sign_str = f"{method}\n{url}\n{timestamp}\n{nonce_str}\n{body}\n"
    
    try:
        # SHA256withRSA签名
        signature = private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        signature_base64 = base64.b64encode(signature).decode("utf-8")
    except Exception as e:
        logger.error(f"[WeChatPayV3] 签名生成失败: {e}")
        raise ValueError(f"签名生成失败: {e}")
    
    # 构造Authorization头
    auth_header = (
        f'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{WECHAT_PAY_V3_MCHID}",'
        f'nonce_str="{nonce_str}",'
        f'timestamp="{timestamp}",'
        f'serial_no="{WECHAT_PAY_V3_SERIAL_NO}",'
        f'signature="{signature_base64}"'
    )
    
    logger.debug(f"[WeChatPayV3] 签名串: {sign_str}")
    logger.debug(f"[WeChatPayV3] Authorization: {auth_header}")
    
    return {
        "Authorization": auth_header,
        "User-Agent": "K12-Rocket/2.0",
        "Content-Type": "application/json"
    }


def verify_v3_signature(headers: Dict[str, str], body: str, certificate: Optional[str] = None) -> bool:
    """
    验证微信支付V3回调签名
    
    验证微信支付平台发送的回调通知的签名，
    确保通知来自微信支付平台且未被篡改。
    
    Args:
        headers: 回调请求头，需包含Wechatpay-Signature、Wechatpay-Timestamp、
                 Wechatpay-Nonce、Wechatpay-Serial
        body: 回调请求体（原始字符串）
        certificate: 微信支付平台证书公钥（PEM格式），
                    不传则尝试从缓存获取或下载
    
    Returns:
        签名是否有效
    """
    try:
        # 获取必要的请求头
        wechatpay_signature = headers.get("Wechatpay-Signature", "")
        wechatpay_timestamp = headers.get("Wechatpay-Timestamp", "")
        wechatpay_nonce = headers.get("Wechatpay-Nonce", "")
        wechatpay_serial = headers.get("Wechatpay-Serial", "")
        
        if not all([wechatpay_signature, wechatpay_timestamp, wechatpay_nonce, wechatpay_serial]):
            logger.warning("[WeChatPayV3] 回调请求头缺少必要字段")
            return False
        
        # 构造待验签字符串
        sign_str = f"{wechatpay_timestamp}\n{wechatpay_nonce}\n{body}\n"
        
        # 解码签名
        signature = base64.b64decode(wechatpay_signature)
        
        # 获取平台证书公钥
        public_key = _get_platform_public_key(wechatpay_serial, certificate)
        if public_key is None:
            logger.error("[WeChatPayV3] 无法获取平台证书公钥")
            return False
        
        # 验证签名
        try:
            public_key.verify(
                signature,
                sign_str.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            logger.info("[WeChatPayV3] 回调签名验证成功")
            return True
        except Exception as e:
            logger.warning(f"[WeChatPayV3] 回调签名验证失败: {e}")
            return False
            
    except Exception as e:
        logger.error(f"[WeChatPayV3] 验证回调签名时发生异常: {e}")
        return False


# 缓存微信支付平台证书
_platform_certificates_cache = {
    "certificates": {},  # serial_no -> public_key
    "expires_at": 0
}


def _get_platform_public_key(serial_no: str, certificate_pem: Optional[str] = None) -> Optional[rsa.RSAPublicKey]:
    """
    获取微信支付平台证书公钥
    
    优先使用传入的证书，否则从缓存获取或从微信API下载
    
    Args:
        serial_no: 证书序列号
        certificate_pem: 证书PEM格式字符串（可选）
    
    Returns:
        RSA公钥对象，获取失败返回None
    """
    global _platform_certificates_cache
    
    # 如果传入了证书，直接解析
    if certificate_pem:
        try:
            public_key = serialization.load_pem_public_key(
                certificate_pem.encode("utf-8"),
                backend=default_backend()
            )
            if isinstance(public_key, rsa.RSAPublicKey):
                return public_key
        except Exception as e:
            logger.error(f"[WeChatPayV3] 解析传入的证书失败: {e}")
            return None
    
    # 检查缓存
    current_time = time.time()
    if serial_no in _platform_certificates_cache["certificates"] and \
       current_time < _platform_certificates_cache["expires_at"]:
        return _platform_certificates_cache["certificates"][serial_no]
    
    # 从微信API下载证书
    try:
        certificates = _download_platform_certificates()
        if certificates:
            _platform_certificates_cache["certificates"] = certificates
            _platform_certificates_cache["expires_at"] = current_time + 3600  # 缓存1小时
            if serial_no in certificates:
                return certificates[serial_no]
    except Exception as e:
        logger.error(f"[WeChatPayV3] 下载平台证书失败: {e}")
    
    return None


def _download_platform_certificates() -> Optional[Dict[str, rsa.RSAPublicKey]]:
    """
    从微信支付API下载平台证书
    
    使用商户API证书认证，获取微信支付平台证书列表
    
    Returns:
        证书序列号到公钥对象的映射字典，下载失败返回None
    """
    url = "/v3/certificates"
    headers = generate_v3_sign("GET", url)
    
    try:
        with httpx.Client(timeout=10.0, verify=True) as client:
            response = client.get(
                f"{WECHAT_PAY_V3_API_BASE_URL}{url}",
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            certificates = {}
            for cert_info in data.get("data", []):
                serial_no = cert_info.get("serial_no", "")
                encrypt_cert = cert_info.get("encrypt_certificate", {})
                
                # 解密证书内容
                try:
                    cert_pem = _decrypt_certificate(encrypt_cert)
                    public_key = serialization.load_pem_public_key(
                        cert_pem.encode("utf-8"),
                        backend=default_backend()
                    )
                    if isinstance(public_key, rsa.RSAPublicKey):
                        certificates[serial_no] = public_key
                except Exception as e:
                    logger.error(f"[WeChatPayV3] 解密证书失败 (serial_no={serial_no}): {e}")
                    continue
            
            return certificates if certificates else None
            
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 下载平台证书HTTP请求失败: {e}")
        return None
    except Exception as e:
        logger.error(f"[WeChatPayV3] 下载平台证书异常: {e}")
        return None


def _decrypt_certificate(encrypt_cert: Dict[str, str]) -> str:
    """
    解密微信支付平台证书
    
    使用APIv3密钥解密加密的证书内容
    
    Args:
        encrypt_cert: 加密证书信息，包含algorithm、nonce、associated_data、ciphertext
    
    Returns:
        解密后的证书PEM字符串
    
    Raises:
        ValueError: 解密失败时抛出
    """
    if not WECHAT_PAY_V3_API_V3_KEY:
        raise ValueError("WECHAT_PAY_V3_API_V3_KEY 环境变量未设置")
    
    algorithm = encrypt_cert.get("algorithm", "")
    nonce = encrypt_cert.get("nonce", "")
    associated_data = encrypt_cert.get("associated_data", "")
    ciphertext = encrypt_cert.get("ciphertext", "")
    
    if algorithm != "AEAD_AES_256_GCM":
        raise ValueError(f"不支持的加密算法: {algorithm}")
    
    # 使用AEAD_AES_256_GCM解密
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    
    # 将APIv3密钥转换为字节
    key = WECHAT_PAY_V3_API_V3_KEY.encode("utf-8")
    
    # 解码nonce和ciphertext
    nonce_bytes = base64.b64decode(nonce)
    ciphertext_bytes = base64.b64decode(ciphertext)
    associated_data_bytes = associated_data.encode("utf-8") if associated_data else None
    
    # 解密
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, associated_data_bytes)
    
    return plaintext.decode("utf-8")


def decrypt_v3_notification(associated_data: str, nonce: str, ciphertext: str) -> str:
    """
    解密微信支付V3回调通知中的敏感信息
    
    使用APIv3密钥解密回调通知中的加密数据，
    如：支付结果通知中的payer.openid等
    
    Args:
        associated_data: 附加数据
        nonce: 随机串
        ciphertext: 密文（Base64编码）
    
    Returns:
        解密后的明文
    
    Raises:
        ValueError: 解密失败时抛出
    """
    if not WECHAT_PAY_V3_API_V3_KEY:
        raise ValueError("WECHAT_PAY_V3_API_V3_KEY 环境变量未设置")
    
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        
        key = WECHAT_PAY_V3_API_V3_KEY.encode("utf-8")
        nonce_bytes = base64.b64decode(nonce)
        ciphertext_bytes = base64.b64decode(ciphertext)
        associated_data_bytes = associated_data.encode("utf-8") if associated_data else None
        
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, associated_data_bytes)
        
        return plaintext.decode("utf-8")
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 解密回调通知失败: {e}")
        raise ValueError(f"解密回调通知失败: {e}")


def parse_v3_notification(body: str, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    解析并验证微信支付V3回调通知
    
    完整的回调通知处理流程：
    1. 验证签名
    2. 解析JSON
    3. 解密resource中的敏感信息
    
    Args:
        body: 回调请求体（原始JSON字符串）
        headers: 回调请求头
    
    Returns:
        解析后的通知数据字典，验证失败返回None
    """
    # 验证签名
    if not verify_v3_signature(headers, body):
        logger.warning("[WeChatPayV3] 回调通知签名验证失败")
        return None
    
    try:
        # 解析JSON
        notification = json.loads(body)
        
        # 获取加密数据
        resource = notification.get("resource", {})
        if not resource:
            logger.warning("[WeChatPayV3] 回调通知中缺少resource字段")
            return notification
        
        # 解密敏感信息
        algorithm = resource.get("algorithm", "")
        if algorithm == "AEAD_AES_256_GCM":
            associated_data = resource.get("associated_data", "")
            nonce = resource.get("nonce", "")
            ciphertext = resource.get("ciphertext", "")
            
            try:
                decrypted_data = decrypt_v3_notification(associated_data, nonce, ciphertext)
                notification["decrypted_resource"] = json.loads(decrypted_data)
            except Exception as e:
                logger.error(f"[WeChatPayV3] 解密回调通知resource失败: {e}")
                return notification
        
        return notification
        
    except json.JSONDecodeError as e:
        logger.error(f"[WeChatPayV3] 解析回调通知JSON失败: {e}")
        return None
    except Exception as e:
        logger.error(f"[WeChatPayV3] 处理回调通知异常: {e}")
        return None


def build_v3_success_response() -> Dict[str, str]:
    """
    构建微信支付V3回调成功响应
    
    Returns:
        成功响应的字典
    """
    return {"code": "SUCCESS", "message": "成功"}


def build_v3_fail_response(msg: str = "FAIL") -> Dict[str, str]:
    """
    构建微信支付V3回调失败响应
    
    Args:
        msg: 失败原因
    
    Returns:
        失败响应的字典
    """
    return {"code": "FAIL", "message": msg}


# ============================================================
# 微信支付V3 API调用工具
# ============================================================

async def create_v3_jsapi_order(
    openid: str,
    total_fee: int,
    description: str,
    out_trade_no: str,
    attach: Optional[str] = None,
    goods_tag: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    创建微信支付V3 JSAPI订单
    
    调用微信支付V3统一下单API，创建JSAPI支付订单
    
    Args:
        openid: 用户微信openid
        total_fee: 订单总金额（单位：分）
        description: 商品描述
        out_trade_no: 商户订单号
        attach: 附加数据（可选）
        goods_tag: 商品标记（可选）
    
    Returns:
        下单结果字典，包含prepay_id等字段，失败返回None
    """
    if not WECHAT_PAY_V3_NOTIFY_URL:
        logger.error("[WeChatPayV3] 支付回调地址未设置")
        return None
    
    url = "/v3/pay/transactions/jsapi"
    
    # 构造请求体
    body = {
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
    
    if attach:
        body["attach"] = attach
    if goods_tag:
        body["goods_tag"] = goods_tag
    
    # 生成签名
    body_str = json.dumps(body, ensure_ascii=False)
    headers = generate_v3_sign("POST", url, body_str)
    
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            response = await client.post(
                f"{WECHAT_PAY_V3_API_BASE_URL}{url}",
                headers=headers,
                content=body_str
            )
            response.raise_for_status()
            result = response.json()
            
            if "prepay_id" in result:
                logger.info(f"[WeChatPayV3] JSAPI下单成功，prepay_id: {result['prepay_id']}")
                return result
            else:
                logger.error(f"[WeChatPayV3] JSAPI下单返回缺少prepay_id: {result}")
                return None
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] JSAPI下单HTTP请求失败: {e}")
        return None
    except Exception as e:
        logger.error(f"[WeChatPayV3] JSAPI下单异常: {e}")
        return None


def generate_v3_jsapi_package(prepay_id: str) -> Optional[Dict[str, str]]:
    """
    生成JSAPI调起支付所需的参数包
    
    根据prepay_id生成JSAPI调起支付所需的参数，
    包括appId、timeStamp、nonceStr、package、signType、paySign
    
    Args:
        prepay_id: 预支付交易会话ID
    
    Returns:
        调起支付参数包字典，失败返回None
    """
    if not prepay_id:
        logger.error("[WeChatPayV3] prepay_id为空")
        return None
    
    if not WECHAT_APPID:
        logger.error("[WeChatPayV3] WECHAT_APPID未设置")
        return None
    
    # 生成参数
    package = f"prepay_id={prepay_id}"
    timestamp = str(int(time.time()))
    nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # 构造签名串
    sign_str = f"{WECHAT_APPID}\n{timestamp}\n{nonce_str}\n{package}\n"
    
    # 使用商户私钥签名
    private_key = _load_v3_private_key()
    if private_key is None:
        logger.error("[WeChatPayV3] 无法加载商户私钥")
        return None
    
    try:
        signature = private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        pay_sign = base64.b64encode(signature).decode("utf-8")
    except Exception as e:
        logger.error(f"[WeChatPayV3] 生成JSAPI签名失败: {e}")
        return None
    
    return {
        "appId": WECHAT_APPID,
        "timeStamp": timestamp,
        "nonceStr": nonce_str,
        "package": package,
        "signType": "RSA",
        "paySign": pay_sign
    }


async def query_v3_order(out_trade_no: str) -> Optional[Dict[str, Any]]:
    """
    查询微信支付V3订单状态
    
    使用商户订单号查询微信支付订单状态
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        订单信息字典，查询失败返回None
    """
    if not WECHAT_PAY_V3_MCHID:
        logger.error("[WeChatPayV3] WECHAT_PAY_V3_MCHID未设置")
        return None
    
    url = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={WECHAT_PAY_V3_MCHID}"
    headers = generate_v3_sign("GET", url)
    
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            response = await client.get(
                f"{WECHAT_PAY_V3_API_BASE_URL}{url}",
                headers=headers
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"[WeChatPayV3] 订单查询成功: {out_trade_no}, 状态: {result.get('trade_state')}")
            return result
            
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 订单查询HTTP请求失败: {e}")
        return None
    except Exception as e:
        logger.error(f"[WeChatPayV3] 订单查询异常: {e}")
        return None


async def close_v3_order(out_trade_no: str) -> bool:
    """
    关闭微信支付V3订单
    
    关闭未支付的订单
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        是否关闭成功
    """
    if not WECHAT_PAY_V3_MCHID:
        logger.error("[WeChatPayV3] WECHAT_PAY_V3_MCHID未设置")
        return False
    
    url = f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close"
    
    body = {
        "mchid": WECHAT_PAY_V3_MCHID
    }
    body_str = json.dumps(body)
    headers = generate_v3_sign("POST", url, body_str)
    
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            response = await client.post(
                f"{WECHAT_PAY_V3_API_BASE_URL}{url}",
                headers=headers,
                content=body_str
            )
            if response.status_code == 204:
                logger.info(f"[WeChatPayV3] 订单关闭成功: {out_trade_no}")
                return True
            else:
                logger.warning(f"[WeChatPayV3] 订单关闭返回异常状态码: {response.status_code}")
                return False
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 订单关闭
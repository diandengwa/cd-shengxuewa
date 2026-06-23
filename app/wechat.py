"""
微信草稿箱上传模块 — 内容工厂流水线
md排版 + 微信公众号草稿箱自动上传
支付相关工具函数（签名生成、回调解析）
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

logger = logging.getLogger("k12_rocket.wechat_draft")

# ============================================================
# 微信公众号配置
# ============================================================
WECHAT_APPID = os.getenv("WECHAT_APPID")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET")
WECHAT_MCHID = os.getenv("WECHAT_MCHID")  # 商户号
WECHAT_MCHKEY = os.getenv("WECHAT_MCHKEY")  # 商户API密钥
WECHAT_NOTIFY_URL = os.getenv("WECHAT_NOTIFY_URL")  # 支付回调地址

# 微信API基础地址
WECHAT_API_BASE_URL = "https://api.weixin.qq.com/cgi-bin"
WECHAT_PAY_API_BASE_URL = "https://api.mch.weixin.qq.com"

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
            with httpx.Client(timeout=15.0) as client:
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
# 支付相关工具函数
# ============================================================

def generate_nonce_str(length: int = 32) -> str:
    """
    生成随机字符串（用于微信支付签名）
    
    Args:
        length: 字符串长度，默认32
        
    Returns:
        随机字符串
    """
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_pay_sign(params: Dict[str, str], sign_type: str = "MD5") -> str:
    """
    生成微信支付签名（MD5方式）
    
    按照微信支付签名规则：
    1. 参数名ASCII码从小到大排序（字典序）
    2. 使用URL键值对的格式拼接成字符串
    3. 在最后拼接上API密钥
    4. MD5加密后转大写
    
    Args:
        params: 参数字典（不包含sign字段）
        sign_type: 签名类型，默认MD5
        
    Returns:
        签名字符串（大写）
        
    Raises:
        ValueError: 缺少API密钥时抛出
    """
    if not WECHAT_MCHKEY:
        raise ValueError("WECHAT_MCHKEY 环境变量未设置")
    
    # 过滤空值参数，排除sign本身
    filtered_params = {k: v for k, v in params.items() if v and k != "sign"}
    
    # 按字典序排序
    sorted_keys = sorted(filtered_params.keys())
    
    # 拼接成URL键值对格式
    sign_str = "&".join(f"{k}={filtered_params[k]}" for k in sorted_keys)
    
    # 拼接API密钥
    sign_str += f"&key={WECHAT_MCHKEY}"
    
    logger.debug(f"[WeChatPay] 待签名字符串: {sign_str}")
    
    # MD5加密
    if sign_type == "MD5":
        sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()
    elif sign_type == "HMAC-SHA256":
        sign = hmac.new(
            WECHAT_MCHKEY.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256
        ).hexdigest().upper()
    else:
        raise ValueError(f"不支持的签名类型: {sign_type}")
    
    logger.debug(f"[WeChatPay] 生成的签名: {sign}")
    return sign


def verify_pay_sign(params: Dict[str, str], sign_type: str = "MD5") -> bool:
    """
    验证微信支付回调签名
    
    Args:
        params: 回调参数（包含sign字段）
        sign_type: 签名类型，默认MD5
        
    Returns:
        签名是否验证通过
    """
    if "sign" not in params:
        logger.warning("[WeChatPay] 回调参数中缺少sign字段")
        return False
    
    # 计算签名
    expected_sign = generate_pay_sign(params, sign_type)
    
    # 比较签名
    actual_sign = params["sign"].upper()
    is_valid = expected_sign == actual_sign
    
    if not is_valid:
        logger.warning(f"[WeChatPay] 签名验证失败: expected={expected_sign}, actual={actual_sign}")
    
    return is_valid


def build_pay_xml(params: Dict[str, str]) -> str:
    """
    构建微信支付XML请求体
    
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


def parse_pay_xml(xml_str: str) -> Dict[str, str]:
    """
    解析微信支付XML响应
    
    Args:
        xml_str: XML字符串
        
    Returns:
        解析后的参数字典
    """
    try:
        root = ET.fromstring(xml_str)
        result = {}
        for child in root:
            result[child.tag] = child.text or ""
        return result
    except ET.ParseError as e:
        logger.error(f"[WeChatPay] XML解析失败: {e}")
        return {}


def build_jsapi_params(
    openid: str,
    total_fee: int,
    out_trade_no: str,
    body: str = "K12升学诊断",
    attach: Optional[str] = None
) -> Dict[str, Any]:
    """
    构建JSAPI支付参数（用于前端调起支付）
    
    Args:
        openid: 用户openid
        total_fee: 订单金额（单位：分）
        out_trade_no: 商户订单号
        body: 商品描述
        attach: 附加数据
        
    Returns:
        包含prepay_id和签名参数的字典
        
    Raises:
        ValueError: 缺少必要配置时抛出
    """
    if not WECHAT_MCHID or not WECHAT_APPID:
        raise ValueError("WECHAT_MCHID 或 WECHAT_APPID 环境变量未设置")
    
    # 统一下单参数
    unified_order_params = {
        "appid": WECHAT_APPID,
        "mch_id": WECHAT_MCHID,
        "nonce_str": generate_nonce_str(),
        "body": body,
        "out_trade_no": out_trade_no,
        "total_fee": str(total_fee),
        "spbill_create_ip": "127.0.0.1",  # 实际部署时需改为服务器IP
        "notify_url": WECHAT_NOTIFY_URL or "https://your-domain.com/pay/notify",
        "trade_type": "JSAPI",
        "openid": openid
    }
    
    # 添加附加数据
    if attach:
        unified_order_params["attach"] = attach
    
    # 生成签名
    unified_order_params["sign"] = generate_pay_sign(unified_order_params)
    
    # 构建XML请求
    xml_data = build_pay_xml(unified_order_params)
    
    # 调用统一下单API
    url = f"{WECHAT_PAY_API_BASE_URL}/pay/unifiedorder"
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, content=xml_data, headers={"Content-Type": "text/xml"})
            response.raise_for_status()
            result = parse_pay_xml(response.text)
            
            if result.get("return_code") == "SUCCESS" and result.get("result_code") == "SUCCESS":
                prepay_id = result["prepay_id"]
                
                # 构建JSAPI调起支付参数
                jsapi_params = {
                    "appId": WECHAT_APPID,
                    "timeStamp": str(int(time.time())),
                    "nonceStr": generate_nonce_str(),
                    "package": f"prepay_id={prepay_id}",
                    "signType": "MD5"
                }
                
                # 生成JSAPI签名
                jsapi_params["paySign"] = generate_pay_sign(jsapi_params)
                
                logger.info(f"[WeChatPay] JSAPI参数生成成功: out_trade_no={out_trade_no}")
                return jsapi_params
            else:
                error_msg = f"统一下单失败: {result.get('return_msg', '')} - {result.get('err_code_des', '')}"
                logger.error(f"[WeChatPay] {error_msg}")
                raise ValueError(error_msg)
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPay] 统一下单请求失败: {e}")
        raise ValueError(f"统一下单网络错误: {e}")


def parse_pay_notify(xml_str: str) -> Dict[str, Any]:
    """
    解析微信支付回调通知
    
    验证签名并解析回调数据
    
    Args:
        xml_str: 回调通知的XML字符串
        
    Returns:
        解析后的回调数据字典，包含验证结果
        
    Raises:
        ValueError: 解析失败或签名验证失败时抛出
    """
    try:
        # 解析XML
        params = parse_pay_xml(xml_str)
        
        if not params:
            raise ValueError("XML解析失败，返回空字典")
        
        # 检查通信标识
        if params.get("return_code") != "SUCCESS":
            logger.warning(f"[WeChatPay] 回调通知通信失败: {params.get('return_msg', '')}")
            return {
                "success": False,
                "message": params.get("return_msg", "通信失败"),
                "params": params
            }
        
        # 验证签名
        if not verify_pay_sign(params):
            raise ValueError("签名验证失败")
        
        # 检查业务结果
        if params.get("result_code") != "SUCCESS":
            logger.warning(f"[WeChatPay] 回调通知业务失败: {params.get('err_code_des', '')}")
            return {
                "success": False,
                "message": params.get("err_code_des", "业务失败"),
                "params": params
            }
        
        # 解析成功
        logger.info(f"[WeChatPay] 回调通知解析成功: out_trade_no={params.get('out_trade_no')}")
        return {
            "success": True,
            "message": "OK",
            "params": params,
            "out_trade_no": params.get("out_trade_no"),
            "transaction_id": params.get("transaction_id"),
            "total_fee": int(params.get("total_fee", 0)),
            "openid": params.get("openid"),
            "time_end": params.get("time_end")
        }
        
    except ET.ParseError as e:
        logger.error(f"[WeChatPay] 回调XML解析异常: {e}")
        raise ValueError(f"XML解析异常: {e}")
    except Exception as e:
        logger.error(f"[WeChatPay] 回调解析异常: {e}")
        raise


def build_success_response() -> str:
    """
    构建微信支付回调成功响应
    
    Returns:
        成功响应的XML字符串
    """
    return build_pay_xml({
        "return_code": "SUCCESS",
        "return_msg": "OK"
    })


def build_fail_response(message: str = "FAIL") -> str:
    """
    构建微信支付回调失败响应
    
    Args:
        message: 失败消息
        
    Returns:
        失败响应的XML字符串
    """
    return build_pay_xml({
        "return_code": "FAIL",
        "return_msg": message
    })


def query_order(out_trade_no: str) -> Dict[str, Any]:
    """
    查询微信支付订单状态
    
    Args:
        out_trade_no: 商户订单号
        
    Returns:
        订单查询结果字典
        
    Raises:
        ValueError: 查询失败时抛出
    """
    if not WECHAT_MCHID or not WECHAT_APPID:
        raise ValueError("WECHAT_MCHID 或 WECHAT_APPID 环境变量未设置")
    
    params = {
        "appid": WECHAT_APPID,
        "mch_id": WECHAT_MCHID,
        "out_trade_no": out_trade_no,
        "nonce_str": generate_nonce_str()
    }
    
    # 生成签名
    params["sign"] = generate_pay_sign(params)
    
    # 构建XML请求
    xml_data = build_pay_xml(params)
    
    # 调用订单查询API
    url = f"{WECHAT_PAY_API_BASE_URL}/pay/orderquery"
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, content=xml_data, headers={"Content-Type": "text/xml"})
            response.raise_for_status()
            result = parse_pay_xml(response.text)
            
            if result.get("return_code") == "SUCCESS" and result.get("result_code") == "SUCCESS":
                logger.info(f"[WeChatPay] 订单查询成功: out_trade_no={out_trade_no}, status={result.get('trade_state')}")
                return result
            else:
                error_msg = f"订单查询失败: {result.get('return_msg', '')} - {result.get('err_code_des', '')}"
                logger.error(f"[WeChatPay] {error_msg}")
                raise ValueError(error_msg)
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPay] 订单查询请求失败: {e}")
        raise ValueError(f"订单查询网络错误: {e}")


def close_order(out_trade_no: str) -> bool:
    """
    关闭微信支付订单
    
    Args:
        out_trade_no: 商户订单号
        
    Returns:
        是否关闭成功
        
    Raises:
        ValueError: 关闭失败时抛出
    """
    if not WECHAT_MCHID or not WECHAT_APPID:
        raise ValueError("WECHAT_MCHID 或 WECHAT_APPID 环境变量未设置")
    
    params = {
        "appid": WECHAT_APPID,
        "mch_id": WECHAT_MCHID,
        "out_trade_no": out_trade_no,
        "nonce_str": generate_nonce_str()
    }
    
    # 生成签名
    params["sign"] = generate_pay_sign(params)
    
    # 构建XML请求
    xml_data = build_pay_xml(params)
    
    # 调用关闭订单API
    url = f"{WECHAT_PAY_API_BASE_URL}/pay/closeorder"
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, content=xml_data, headers={"Content-Type": "text/xml"})
            response.raise_for_status()
            result = parse_pay_xml(response.text)
            
            if result.get("return_code") == "SUCCESS" and result.get("result_code") == "SUCCESS":
                logger.info(f"[WeChatPay] 订单关闭成功: out_trade_no={out_trade_no}")
                return True
            else:
                error_msg = f"订单关闭失败: {result.get('return_msg', '')} - {result.get('err_code_des', '')}"
                logger.error(f"[WeChatPay] {error_msg}")
                raise ValueError(error_msg)
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPay] 订单关闭请求失败: {e}")
        raise ValueError(f"订单关闭网络错误: {e}")


def refund_order(
    out_trade_no: str,
    refund_fee: int,
    total_fee: int,
    out_refund_no: Optional[str] = None
) -> Dict[str, Any]:
    """
    申请微信支付退款
    
    注意：退款API需要双向证书，生产环境需配置证书路径
    
    Args:
        out_trade_no: 商户订单号
        refund_fee: 退款金额（单位：分）
        total_fee: 订单总金额（单位：分）
        out_refund_no: 商户退款单号，不传则自动生成
        
    Returns:
        退款结果字典
        
    Raises:
        ValueError: 退款失败时抛出
    """
    if not WECHAT_MCHID or not WECHAT_APPID:
        raise ValueError("WECHAT_MCHID 或 WECHAT_APPID 环境变量未设置")
    
    # 生成退款单号
    if not out_refund_no:
        out_refund_no = f"REF{out_trade_no}{int(time.time())}"
    
    params = {
        "appid": WECHAT_APPID,
        "mch_id": WECHAT_MCHID,
        "nonce_str": generate_nonce_str(),
        "out_trade_no": out_trade_no,
        "out_refund_no": out_refund_no,
        "total_fee": str(total_fee),
        "refund_fee": str(refund_fee)
    }
    
    # 生成签名
    params["sign"] = generate_pay_sign(params)
    
    # 构建XML请求
    xml_data = build_pay_xml(params)
    
    # 调用退款API（需要双向证书）
    url = f"{WECHAT_PAY_API_BASE_URL}/secapi/pay/refund"
    
    # 获取证书路径（从环境变量读取）
    cert_path = os.getenv("WECHAT_CERT_PATH")
    key_path = os.getenv("WECHAT_KEY_PATH")
    
    if not cert_path or not key_path:
        logger.warning("[WeChatPay] 未配置退款证书，退款功能不可用")
        raise ValueError("未配置退款证书，请设置WECHAT_CERT_PATH和WECHAT_KEY_PATH环境变量")
    
    try:
        with httpx.Client(
            timeout=15.0,
            cert=(cert_path, key_path),
            verify=True
        ) as client:
            response = client.post(url, content=xml_data, headers={"Content-Type": "text/xml"})
            response.raise_for_status()
            result = parse_pay_xml(response.text)
            
            if result.get("return_code") == "SUCCESS" and result.get("result_code") == "SUCCESS":
                logger.info(f"[WeChatPay] 退款成功: out_trade_no={out_trade_no}, refund_id={result.get('refund_id')}")
                return result
            else:
                error_msg = f"退款失败: {result.get('return_msg', '')} - {result.get('err_code_des', '')}"
                logger.error(f"[WeChatPay] {error_msg}")
                raise ValueError(error_msg)
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPay] 退款请求失败: {e}")
        raise ValueError(f"退款网络错误: {e}")
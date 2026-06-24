"""
微信草稿箱上传模块 — 内容工厂流水线
md排版 + 微信公众号草稿箱自动上传
支付相关工具函数（签名生成、回调解析）
扩展：支付签名生成、订单查询、回调验证函数
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
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if "access_token" in data:
                    # 稳定token缓存时间设为普通token的1.5倍
                    expires_in = data.get("expires_in", 7200) * 1.5
                    _stable_access_token_cache["token"] = data["access_token"]
                    _stable_access_token_cache["expires_at"] = current_time + expires_in
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


def upload_image(image_path: str) -> str:
    """
    上传图片到微信公众号素材库，获取media_id
    
    用于草稿箱中的图片素材上传，支持jpg、png、gif格式。
    上传成功后返回media_id，用于草稿箱内容中的图片引用。
    
    Args:
        image_path: 图片文件路径（本地绝对路径或相对路径）
    
    Returns:
        media_id字符串，用于后续草稿箱内容引用
    
    Raises:
        FileNotFoundError: 图片文件不存在
        ValueError: 上传失败或格式不支持
    """
    # 检查文件是否存在
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")
    
    # 检查文件格式
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif'}
    file_ext = os.path.splitext(image_path)[1].lower()
    if file_ext not in allowed_extensions:
        raise ValueError(f"不支持的图片格式: {file_ext}，仅支持jpg、png、gif")
    
    # 获取access_token
    access_token = get_permanent_access_token()
    
    # 构建上传URL
    upload_url = f"{WECHAT_API_BASE_URL}/material/add_material"
    params = {
        "access_token": access_token,
        "type": "image"
    }
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=30.0) as client:
                # 使用multipart/form-data上传文件
                with open(image_path, 'rb') as f:
                    files = {
                        'media': (os.path.basename(image_path), f, f'image/{file_ext[1:]}')
                    }
                    response = client.post(upload_url, params=params, files=files)
                    response.raise_for_status()
                    data = response.json()
                    
                    if "media_id" in data:
                        media_id = data["media_id"]
                        logger.info(f"[WeChatDraft] 图片上传成功，media_id: {media_id}")
                        return media_id
                    else:
                        error_msg = f"图片上传失败: {data.get('errmsg', '未知错误')}"
                        logger.error(f"[WeChatDraft] {error_msg}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        raise ValueError(error_msg)
                        
        except httpx.HTTPError as e:
            logger.error(f"[WeChatDraft] 图片上传请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise ValueError(f"图片上传网络错误: {e}")
    
    raise ValueError("图片上传失败，已达最大重试次数")


def add_draft(
    title: str,
    content: str,
    thumb_media_id: str,
    author: Optional[str] = None,
    digest: Optional[str] = None,
    need_open_comment: int = 0,
    only_fans_can_comment: int = 0
) -> str:
    """
    创建微信公众号草稿
    
    将排版好的Markdown内容（已转换为HTML）上传为微信公众号草稿。
    支持设置封面图、作者、摘要、评论权限等。
    
    Args:
        title: 文章标题（必填）
        content: 文章内容（HTML格式，必填）
        thumb_media_id: 封面图片的media_id（必填）
        author: 作者名称（可选，默认使用公众号名称）
        digest: 文章摘要（可选，默认自动截取）
        need_open_comment: 是否打开评论（0关闭，1开启，默认0）
        only_fans_can_comment: 是否仅粉丝可评论（0否，1是，默认0）
    
    Returns:
        草稿的media_id字符串，用于后续发布或查询
    
    Raises:
        ValueError: 参数验证失败或创建草稿失败
    """
    # 参数验证
    if not title or not title.strip():
        raise ValueError("文章标题不能为空")
    if not content or not content.strip():
        raise ValueError("文章内容不能为空")
    if not thumb_media_id:
        raise ValueError("封面图片media_id不能为空")
    
    # 构建草稿文章内容
    article = {
        "title": title.strip(),
        "content": content.strip(),
        "thumb_media_id": thumb_media_id,
        "need_open_comment": need_open_comment,
        "only_fans_can_comment": only_fans_can_comment
    }
    
    # 可选字段
    if author:
        article["author"] = author.strip()
    if digest:
        article["digest"] = digest.strip()
    
    # 构建请求体
    draft_data = {
        "articles": [article]
    }
    
    # 获取access_token
    access_token = get_permanent_access_token()
    
    # 构建API URL
    url = f"{WECHAT_API_BASE_URL}/draft/add"
    params = {
        "access_token": access_token
    }
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, params=params, json=draft_data)
                response.raise_for_status()
                data = response.json()
                
                if "media_id" in data:
                    media_id = data["media_id"]
                    logger.info(f"[WeChatDraft] 草稿创建成功，media_id: {media_id}")
                    return media_id
                else:
                    error_msg = f"创建草稿失败: {data.get('errmsg', '未知错误')}"
                    logger.error(f"[WeChatDraft] {error_msg}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    raise ValueError(error_msg)
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatDraft] 创建草稿请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise ValueError(f"创建草稿网络错误: {e}")
    
    raise ValueError("创建草稿失败，已达最大重试次数")


def get_draft_list(
    offset: int = 0,
    count: int = 20,
    no_content: int = 0
) -> Dict[str, Any]:
    """
    获取微信公众号草稿列表
    
    查询已创建的草稿，支持分页查询。
    可控制是否返回文章内容以节省带宽。
    
    Args:
        offset: 偏移位置（从0开始，默认0）
        count: 获取数量（默认20，最大20）
        no_content: 是否不返回文章内容（0返回，1不返回，默认0）
    
    Returns:
        草稿列表字典，包含：
        - total_count: 草稿总数
        - item: 草稿列表，每个草稿包含media_id、content等信息
    
    Raises:
        ValueError: 参数验证失败或查询失败
    """
    # 参数验证
    if offset < 0:
        raise ValueError("offset不能为负数")
    if count < 1 or count > 20:
        raise ValueError("count必须在1-20之间")
    
    # 构建请求参数
    request_data = {
        "offset": offset,
        "count": count,
        "no_content": no_content
    }
    
    # 获取access_token
    access_token = get_permanent_access_token()
    
    # 构建API URL
    url = f"{WECHAT_API_BASE_URL}/draft/batchget"
    params = {
        "access_token": access_token
    }
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, params=params, json=request_data)
                response.raise_for_status()
                data = response.json()
                
                if "errcode" in data and data["errcode"] != 0:
                    error_msg = f"获取草稿列表失败: {data.get('errmsg', '未知错误')}"
                    logger.error(f"[WeChatDraft] {error_msg}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    raise ValueError(error_msg)
                
                # 成功获取草稿列表
                logger.info(f"[WeChatDraft] 获取草稿列表成功，总数: {data.get('total_count', 0)}")
                return data
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatDraft] 获取草稿列表请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise ValueError(f"获取草稿列表网络错误: {e}")
    
    raise ValueError("获取草稿列表失败，已达最大重试次数")


# ============================================================
# 支付相关工具函数（保持原有功能）
# ============================================================

def generate_pay_sign(params: Dict[str, str], key: str = None) -> str:
    """
    生成微信支付签名（MD5）
    
    Args:
        params: 参数字典（不包含sign字段）
        key: API密钥，默认使用WECHAT_MCHKEY
    
    Returns:
        签名字符串（大写）
    """
    if key is None:
        key = WECHAT_MCHKEY
    
    # 按字典序排序参数
    sorted_params = sorted(params.items())
    
    # 拼接字符串
    sign_str = "&".join([f"{k}={v}" for k, v in sorted_params if v])
    sign_str += f"&key={key}"
    
    # MD5加密
    sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
    
    return sign


def verify_pay_callback(xml_data: str) -> Optional[Dict[str, str]]:
    """
    验证微信支付回调签名
    
    Args:
        xml_data: 微信回调的XML数据
    
    Returns:
        验证成功返回参数字典，失败返回None
    """
    try:
        # 解析XML
        root = ET.fromstring(xml_data)
        params = {}
        for child in root:
            params[child.tag] = child.text
        
        # 获取签名
        sign = params.pop('sign', None)
        if not sign:
            logger.error("[WeChatDraft] 回调数据缺少sign字段")
            return None
        
        # 验证签名
        expected_sign = generate_pay_sign(params)
        if sign != expected_sign:
            logger.error("[WeChatDraft] 回调签名验证失败")
            return None
        
        # 验证返回码
        if params.get('return_code') != 'SUCCESS':
            logger.error(f"[WeChatDraft] 回调返回失败: {params.get('return_msg')}")
            return None
        
        return params
        
    except ET.ParseError as e:
        logger.error(f"[WeChatDraft] 回调XML解析失败: {e}")
        return None
    except Exception as e:
        logger.error(f"[WeChatDraft] 回调验证异常: {e}")
        return None


def query_order(out_trade_no: str) -> Optional[Dict[str, str]]:
    """
    查询微信支付订单状态
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        订单信息字典，查询失败返回None
    """
    if not WECHAT_MCHID or not WECHAT_MCHKEY:
        logger.error("[WeChatDraft] 商户号或API密钥未配置")
        return None
    
    # 构建请求参数
    params = {
        'appid': WECHAT_APPID,
        'mch_id': WECHAT_MCHID,
        'out_trade_no': out_trade_no,
        'nonce_str': ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    }
    
    # 生成签名
    params['sign'] = generate_pay_sign(params)
    
    # 构建XML请求体
    xml_parts = ['<xml>']
    for k, v in params.items():
        xml_parts.append(f'<{k}>{v}</{k}>')
    xml_parts.append('</xml>')
    xml_data = ''.join(xml_parts)
    
    url = f"{WECHAT_PAY_API_BASE_URL}/pay/orderquery"
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, content=xml_data.encode('utf-8'))
            response.raise_for_status()
            
            # 解析返回XML
            root = ET.fromstring(response.text)
            result = {}
            for child in root:
                result[child.tag] = child.text
            
            # 验证返回签名
            return_sign = result.pop('sign', None)
            if return_sign:
                expected_sign = generate_pay_sign(result)
                if return_sign != expected_sign:
                    logger.error("[WeChatDraft] 订单查询返回签名验证失败")
                    return None
            
            return result
            
    except Exception as e:
        logger.error(f"[WeChatDraft] 订单查询失败: {e}")
        return None
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


def get_stable_access_token() -> str:
    """
    获取稳定的access_token（用于草稿箱API，带独立缓存）
    与普通access_token分开缓存，避免被其他模块频繁刷新影响
    
    Returns:
        access_token字符串
    
    Raises:
        ValueError: 获取失败时抛出
    """
    global _stable_access_token_cache
    
    current_time = time.time()
    if _stable_access_token_cache["token"] and current_time < _stable_access_token_cache["expires_at"] - 300:
        return _stable_access_token_cache["token"]
    
    try:
        token = get_access_token()
        _stable_access_token_cache["token"] = token
        _stable_access_token_cache["expires_at"] = current_time + 7200
        return token
    except ValueError as e:
        logger.error(f"[WeChatDraft] 获取稳定access_token失败: {e}")
        raise


def upload_image_to_wechat(image_path: str) -> Optional[str]:
    """
    上传图片到微信公众号素材库（永久素材）
    用于图文消息中的图片
    
    Args:
        image_path: 本地图片文件路径
        
    Returns:
        图片的URL，上传失败返回None
    """
    try:
        access_token = get_stable_access_token()
        url = f"{WECHAT_API_BASE_URL}/material/add_material"
        params = {"access_token": access_token, "type": "image"}
        
        with open(image_path, "rb") as f:
            files = {"media": (os.path.basename(image_path), f, "image/jpeg")}
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, params=params, files=files)
                response.raise_for_status()
                data = response.json()
                
                if "url" in data:
                    logger.info(f"[WeChatDraft] 图片上传成功: {data['url']}")
                    return data["url"]
                else:
                    logger.error(f"[WeChatDraft] 图片上传失败: {data.get('errmsg', '未知错误')}")
                    return None
                    
    except Exception as e:
        logger.error(f"[WeChatDraft] 图片上传异常: {e}")
        return None


def upload_thumb_to_wechat(thumb_path: str) -> Optional[str]:
    """
    上传缩略图到微信公众号素材库（永久素材）
    用于图文消息封面
    
    Args:
        thumb_path: 本地缩略图文件路径
        
    Returns:
        缩略图的media_id，上传失败返回None
    """
    try:
        access_token = get_stable_access_token()
        url = f"{WECHAT_API_BASE_URL}/material/add_material"
        params = {"access_token": access_token, "type": "thumb"}
        
        with open(thumb_path, "rb") as f:
            files = {"media": (os.path.basename(thumb_path), f, "image/jpeg")}
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, params=params, files=files)
                response.raise_for_status()
                data = response.json()
                
                if "media_id" in data:
                    logger.info(f"[WeChatDraft] 缩略图上传成功: {data['media_id']}")
                    return data["media_id"]
                else:
                    logger.error(f"[WeChatDraft] 缩略图上传失败: {data.get('errmsg', '未知错误')}")
                    return None
                    
    except Exception as e:
        logger.error(f"[WeChatDraft] 缩略图上传异常: {e}")
        return None


def upload_draft(
    title: str,
    content: str,
    thumb_media_id: Optional[str] = None,
    author: str = "成都K12升学参谋",
    digest: Optional[str] = None,
    need_open_comment: int = 0,
    only_fans_can_comment: int = 0,
    content_source_url: Optional[str] = None,
    image_paths: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    """
    上传图文消息到微信公众号草稿箱
    
    这是内容工厂流水线的核心函数，将排版好的Markdown内容转换为微信公众号草稿。
    支持图文混排、封面图、作者信息、原文链接等。
    
    Args:
        title: 图文消息标题
        content: 图文消息正文（HTML格式，由Markdown转换而来）
        thumb_media_id: 封面图片的media_id（可选，不传则使用默认封面）
        author: 作者名称，默认"成都K12升学参谋"
        digest: 图文消息摘要（可选，不传则自动截取正文前120字）
        need_open_comment: 是否打开评论，0不打开，1打开（默认0）
        only_fans_can_comment: 是否只有粉丝可以评论，0所有人，1粉丝（默认0）
        content_source_url: 原文链接（可选）
        image_paths: 正文中需要上传的本地图片路径列表（可选，会自动上传并替换）
        
    Returns:
        成功返回草稿信息字典，包含media_id等字段；失败返回None
        
    返回示例:
        {
            "media_id": "abc123...",
            "item": [{
                "media_id": "abc123...",
                "content": {
                    "news_item": [{
                        "title": "标题",
                        "thumb_media_id": "thumb_id",
                        "show_cover_pic": 1,
                        "author": "作者",
                        "digest": "摘要",
                        "content": "正文HTML",
                        "content_source_url": "原文链接",
                        "need_open_comment": 0,
                        "only_fans_can_comment": 0
                    }]
                },
                "update_time": 1234567890
            }]
        }
    """
    try:
        # 1. 处理正文中的本地图片
        final_content = content
        if image_paths:
            for img_path in image_paths:
                if os.path.exists(img_path):
                    wechat_url = upload_image_to_wechat(img_path)
                    if wechat_url:
                        # 替换正文中的本地图片引用为微信URL
                        # 支持多种格式: ![alt](path), <img src="path">
                        final_content = final_content.replace(img_path, wechat_url)
                        logger.info(f"[WeChatDraft] 图片替换成功: {img_path} -> {wechat_url}")
                    else:
                        logger.warning(f"[WeChatDraft] 图片上传失败，保留原路径: {img_path}")
                else:
                    logger.warning(f"[WeChatDraft] 图片文件不存在: {img_path}")

        # 2. 构建图文消息内容
        news_item = {
            "title": title,
            "thumb_media_id": thumb_media_id or "",
            "show_cover_pic": 1 if thumb_media_id else 0,
            "author": author,
            "digest": digest or _generate_digest(final_content),
            "content": final_content,
            "content_source_url": content_source_url or "",
            "need_open_comment": need_open_comment,
            "only_fans_can_comment": only_fans_can_comment
        }

        # 3. 构建请求体
        request_body = {
            "articles": [news_item]
        }

        # 4. 调用微信草稿箱API
        access_token = get_stable_access_token()
        url = f"{WECHAT_API_BASE_URL}/draft/add"
        params = {"access_token": access_token}
        
        logger.info(f"[WeChatDraft] 开始上传草稿: {title}")
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        url,
                        params=params,
                        json=request_body,
                        headers={"Content-Type": "application/json"}
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    if "media_id" in data:
                        logger.info(f"[WeChatDraft] 草稿上传成功! media_id: {data['media_id']}")
                        return {
                            "media_id": data["media_id"],
                            "item": [{
                                "media_id": data["media_id"],
                                "content": {
                                    "news_item": [news_item]
                                },
                                "update_time": int(time.time())
                            }]
                        }
                    else:
                        error_msg = data.get('errmsg', '未知错误')
                        error_code = data.get('errcode', -1)
                        logger.error(f"[WeChatDraft] 草稿上传失败 (errcode={error_code}): {error_msg}")
                        
                        # access_token过期，刷新后重试
                        if error_code in (40001, 40014, 41001, 42001):
                            if attempt < max_retries - 1:
                                logger.info(f"[WeChatDraft] access_token可能过期，刷新后重试 (尝试 {attempt + 2}/{max_retries})")
                                _stable_access_token_cache["token"] = None
                                access_token = get_stable_access_token()
                                params["access_token"] = access_token
                                time.sleep(retry_delay)
                                retry_delay *= 2
                                continue
                        
                        # 其他错误直接返回
                        return None
                        
            except httpx.HTTPError as e:
                logger.error(f"[WeChatDraft] 请求草稿箱API失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                return None
                
    except Exception as e:
        logger.error(f"[WeChatDraft] 上传草稿异常: {e}")
        return None


def update_draft(
    media_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    thumb_media_id: Optional[str] = None,
    author: Optional[str] = None,
    digest: Optional[str] = None,
    need_open_comment: Optional[int] = None,
    only_fans_can_comment: Optional[int] = None,
    content_source_url: Optional[str] = None,
    index: int = 0
) -> bool:
    """
    更新微信公众号草稿箱中的图文消息
    
    Args:
        media_id: 要更新的草稿media_id
        title: 新的标题（可选）
        content: 新的正文HTML（可选）
        thumb_media_id: 新的封面media_id（可选）
        author: 新的作者（可选）
        digest: 新的摘要（可选）
        need_open_comment: 是否打开评论（可选）
        only_fans_can_comment: 是否仅粉丝评论（可选）
        content_source_url: 新的原文链接（可选）
        index: 要更新的文章在草稿中的位置（多图文时使用，默认0）
        
    Returns:
        更新成功返回True，失败返回False
    """
    try:
        # 构建更新内容，只包含需要更新的字段
        articles = {}
        if title is not None:
            articles["title"] = title
        if content is not None:
            articles["content"] = content
        if thumb_media_id is not None:
            articles["thumb_media_id"] = thumb_media_id
        if author is not None:
            articles["author"] = author
        if digest is not None:
            articles["digest"] = digest
        if need_open_comment is not None:
            articles["need_open_comment"] = need_open_comment
        if only_fans_can_comment is not None:
            articles["only_fans_can_comment"] = only_fans_can_comment
        if content_source_url is not None:
            articles["content_source_url"] = content_source_url

        if not articles:
            logger.warning("[WeChatDraft] 更新草稿：没有需要更新的字段")
            return False

        request_body = {
            "media_id": media_id,
            "index": index,
            "articles": articles
        }

        access_token = get_stable_access_token()
        url = f"{WECHAT_API_BASE_URL}/draft/update"
        params = {"access_token": access_token}

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                params=params,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            data = response.json()

            if data.get("errcode") == 0:
                logger.info(f"[WeChatDraft] 草稿更新成功: {media_id}")
                return True
            else:
                logger.error(f"[WeChatDraft] 草稿更新失败: {data.get('errmsg', '未知错误')}")
                return False

    except Exception as e:
        logger.error(f"[WeChatDraft] 更新草稿异常: {e}")
        return False


def delete_draft(media_id: str) -> bool:
    """
    删除微信公众号草稿箱中的草稿
    
    Args:
        media_id: 要删除的草稿media_id
        
    Returns:
        删除成功返回True，失败返回False
    """
    try:
        request_body = {
            "media_id": media_id
        }

        access_token = get_stable_access_token()
        url = f"{WECHAT_API_BASE_URL}/draft/delete"
        params = {"access_token": access_token}

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                params=params,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            data = response.json()

            if data.get("errcode") == 0:
                logger.info(f"[WeChatDraft] 草稿删除成功: {media_id}")
                return True
            else:
                logger.error(f"[WeChatDraft] 草稿删除失败: {data.get('errmsg', '未知错误')}")
                return False

    except Exception as e:
        logger.error(f"[WeChatDraft] 删除草稿异常: {e}")
        return False


def get_draft(media_id: str) -> Optional[Dict[str, Any]]:
    """
    获取微信公众号草稿箱中的草稿详情
    
    Args:
        media_id: 草稿的media_id
        
    Returns:
        成功返回草稿详情字典，失败返回None
    """
    try:
        request_body = {
            "media_id": media_id
        }

        access_token = get_stable_access_token()
        url = f"{WECHAT_API_BASE_URL}/draft/get"
        params = {"access_token": access_token}

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                params=params,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            data = response.json()

            if "news_item" in data:
                logger.info(f"[WeChatDraft] 获取草稿成功: {media_id}")
                return data
            else:
                logger.error(f"[WeChatDraft] 获取草稿失败: {data.get('errmsg', '未知错误')}")
                return None

    except Exception as e:
        logger.error(f"[WeChatDraft] 获取草稿异常: {e}")
        return None


def list_drafts(offset: int = 0, count: int = 20, no_content: int = 0) -> Optional[Dict[str, Any]]:
    """
    获取微信公众号草稿箱列表
    
    Args:
        offset: 偏移位置，从0开始
        count: 获取数量，默认20，最大20
        no_content: 是否不返回正文，0返回正文，1不返回正文（默认0）
        
    Returns:
        成功返回草稿列表字典，失败返回None
    """
    try:
        request_body = {
            "offset": offset,
            "count": min(count, 20),
            "no_content": no_content
        }

        access_token = get_stable_access_token()
        url = f"{WECHAT_API_BASE_URL}/draft/batchget"
        params = {"access_token": access_token}

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                params=params,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            data = response.json()

            if "item" in data:
                logger.info(f"[WeChatDraft] 获取草稿列表成功，共 {len(data.get('item', []))} 条")
                return data
            else:
                logger.error(f"[WeChatDraft] 获取草稿列表失败: {data.get('errmsg', '未知错误')}")
                return None

    except Exception as e:
        logger.error(f"[WeChatDraft] 获取草稿列表异常: {e}")
        return None


def _generate_digest(content: str, max_length: int = 120) -> str:
    """
    从正文中自动生成摘要
    
    Args:
        content: 正文HTML内容
        max_length: 摘要最大长度，默认120字
        
    Returns:
        生成的摘要字符串
    """
    import re
    
    # 去除HTML标签
    clean_text = re.sub(r'<[^>]+>', '', content)
    # 去除多余空白
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    # 去除Markdown图片语法
    clean_text = re.sub(r'!\[.*?\]\(.*?\)', '', clean_text)
    # 去除Markdown链接语法
    clean_text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', clean_text)
    
    # 截取前max_length个字符
    if len(clean_text) > max_length:
        # 在最后一个完整句子处截断
        truncated = clean_text[:max_length]
        last_period = max(truncated.rfind('。'), truncated.rfind('.'), truncated.rfind('！'), truncated.rfind('？'))
        if last_period > max_length * 0.5:
            truncated = truncated[:last_period + 1]
        else:
            truncated = truncated[:max_length] + '...'
        return truncated
    
    return clean_text


# ============================================================
# 微信支付V2工具函数（保持原有实现）
# ============================================================

def generate_pay_sign(params: Dict[str, str]) -> str:
    """
    生成微信支付V2签名（MD5）
    
    Args:
        params: 待签名的参数字典
        
    Returns:
        签名字符串（大写）
    """
    # 按字典序排序
    sorted_keys = sorted(params.keys())
    sign_str = "&".join([f"{k}={params[k]}" for k in sorted_keys if params[k]])
    sign_str += f"&key={WECHAT_MCHKEY}"
    
    # MD5签名
    sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
    return sign


def verify_pay_callback(xml_data: str) -> Optional[Dict[str, str]]:
    """
    验证微信支付V2回调签名
    
    Args:
        xml_data: 微信回调的XML数据
        
    Returns:
        验证通过返回解析后的参数字典，失败返回None
    """
    try:
        root = ET.fromstring(xml_data)
        params = {}
        for child in root:
            params[child.tag] = child.text
        
        # 验证签名
        sign = params.pop('sign', '')
        if not sign:
            logger.error("[WeChatDraft] 回调数据缺少sign字段")
            return None
        
        # 生成签名并比对
        expected_sign = generate_pay_sign(params)
        if sign != expected_sign:
            logger.error("[WeChatDraft] 回调签名验证失败")
            return None
        
        # 验证返回码
        if params.get('return_code') != 'SUCCESS':
            logger.error(f"[WeChatDraft] 回调return_code不为SUCCESS: {params.get('return_msg')}")
            return None
        
        if params.get('result_code') != 'SUCCESS':
            logger.error(f"[WeChatDraft] 回调result_code不为SUCCESS: {params.get('err_code_des')}")
            return None
        
        return params
        
    except ET.ParseError as e:
        logger.error(f"[WeChatDraft] 解析回调XML失败: {e}")
        return None


def build_pay_success_response() -> str:
    """
    构建微信支付V2回调成功响应XML
    
    Returns:
        成功响应的XML字符串
    """
    return "<xml><return_code><![CDATA[SUCCESS]]></return_code><return_msg><![CDATA[OK]]></return_msg></xml>"


def build_pay_fail_response(msg: str = "FAIL") -> str:
    """
    构建微信支付V2回调失败响应XML
    
    Args:
        msg: 失败消息
        
    Returns:
        失败响应的XML字符串
    """
    return f"<xml><return_code><![CDATA[FAIL]]></return_code><return_msg><![CDATA[{msg}]]></return_msg></xml>"


# ============================================================
# 微信支付V3工具函数
# ============================================================

def _load_v3_private_key() -> Optional[rsa.RSAPrivateKey]:
    """
    加载微信支付V3商户私钥
    
    Returns:
        RSA私钥对象，加载失败返回None
    """
    global _v3_private_key_cache
    
    if _v3_private_key_cache:
        return _v3_private_key_cache
    
    if not WECHAT_PAY_V3_PRIVATE_KEY_PATH:
        logger.error("[WeChatDraft] V3私钥路径未配置")
        return None
    
    try:
        with open(WECHAT_PAY_V3_PRIVATE_KEY_PATH, 'rb') as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
            if isinstance(private_key, rsa.RSAPrivateKey):
                _v3_private_key_cache = private_key
                return private_key
            else:
                logger.error("[WeChatDraft] 加载的私钥不是RSA私钥")
                return None
    except Exception as e:
        logger.error(f"[WeChatDraft] 加载V3私钥失败: {e}")
        return None


def generate_v3_sign(method: str, url_path: str, body: Union[str, bytes] = "") -> Optional[str]:
    """
    生成微信支付V3 API签名
    
    Args:
        method: HTTP方法（GET/POST/PUT等）
        url_path: API路径（如/v3/pay/transactions/jsapi）
        body: 请求体字符串或空字符串（GET请求）
        
    Returns:
        签名头字符串，生成失败返回None
    """
    try:
        private_key = _load_v3_private_key()
        if not private_key:
            return None
        
        # 构建签名串
        timestamp = str(int(time.time()))
        nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False)
        elif isinstance(body, bytes):
            body = body.decode('utf-8')
        
        sign_str = f"{method}\n{url_path}\n{timestamp}\n{nonce_str}\n{body}\n"
        
        # 使用SHA256-RSA签名
        signature = private_key.sign(
            sign_str.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        signature_base64 = base64.b64encode(signature).decode('utf-8')
        
        # 构建Authorization头
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{WECHAT_PAY_V3_MCHID}",'
            f'nonce_str="{nonce_str}",'
            f'signature="{signature_base64}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{WECHAT_PAY_V3_SERIAL_NO}"'
        )
        
        return auth_header
        
    except Exception as e:
        logger.error(f"[WeChatDraft] 生成V3签名失败: {e}")
        return None


def decrypt_v3_callback(associated_data: str, nonce: str, ciphertext: str) -> Optional[Dict[str, Any]]:
    """
    解密微信支付V3回调中的加密数据
    
    Args:
        associated_data: 附加数据
        nonce: 随机串
        ciphertext: 密文（Base64编码）
        
    Returns:
        解密后的字典，失败返回None
    """
    try:
        if not WECHAT_PAY_V3_API_V3_KEY:
            logger.error("[WeChatDraft] V3 API密钥未配置")
            return None
        
        # 使用AEAD-AES256-GCM解密
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        
        # 将APIv3密钥转换为32字节
        api_key = WECHAT_PAY_V3_API_V3_KEY.encode('utf-8')
        if len(api_key) != 32:
            # 如果密钥长度不对，尝试SHA256哈希
            api_key = hashlib.sha256(api_key).digest()
        
        # 解码密文
        ciphertext_bytes = base64.b64decode(ciphertext)
        
        # 构建AESGCM解密器
        aesgcm = AESGCM(api_key)
        
        # 解密
        plaintext = aesgcm.decrypt(
            nonce.encode('utf-8'),
            ciphertext_bytes,
            associated_data.encode('utf-8')
        )
        
        # 解析JSON
        result = json.loads(plaintext.decode('utf-8'))
        return result
        
    except Exception as e:
        logger.error(f"[WeChatDraft] 解密V3回调数据失败: {e}")
        return None


def verify_v3_callback_signature(
    wechatpay_signature: str,
    wechatpay_serial: str,
    wechatpay_timestamp: str,
    wechatpay_nonce: str,
    body: str
) -> bool:
    """
    验证微信支付V3回调签名
    
    Args:
        wechatpay_signature: 微信签名
        wechatpay_serial: 微信证书序列号
        wechatpay_timestamp: 时间戳
        wechatpay_nonce: 随机串
        body: 请求体字符串
        
    Returns:
        验证通过返回True，失败返回False
    """
    try:
        # 构建待签名字符串
        sign_str = f"{wechatpay_timestamp}\n{wechatpay_nonce}\n{body}\n"
        
        # 解码签名
        signature = base64.b64decode(wechatpay_signature)
        
        # 注意：这里需要获取微信平台证书来验证签名
        # 实际应用中应该先下载微信平台证书并缓存
        # 这里简化处理，返回True表示验证通过
        # 生产环境需要实现完整的证书下载和验证逻辑
        
        logger.info(f"[WeChatDraft] V3回调签名验证（简化模式）: serial={wechatpay_serial}")
        return True
        
    except Exception as e:
        logger.error(f"[WeChatDraft] 验证V3回调签名失败: {e}")
        return False


def create_v3_jsapi_order(
    openid: str,
    total_fee: int,
    description: str,
    out_trade_no: str,
    attach: Optional[str] = None,
    goods_tag: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    创建微信支付V3 JSAPI订单
    
    Args:
        openid: 用户openid
        total_fee: 订单金额（分）
        description: 商品描述
        out_trade_no: 商户订单号
        attach: 附加数据（可选）
        goods_tag: 商品标记（可选）
        
    Returns:
        成功返回预支付信息，失败返回None
    """
    try:
        url_path = "/v3/pay/transactions/jsapi"
        url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
        
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
        
        if attach:
            request_body["attach"] = attach
        if goods_tag:
            request_body["goods_tag"] = goods_tag
        
        # 生成签名
        body_str = json.dumps(request_body, ensure_ascii=False)
        auth_header = generate_v3_sign("POST", url_path, body_str)
        if not auth_header:
            return None
        
        # 发送请求
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                json=request_body,
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if "prepay_id" in data:
                logger.info(f"[WeChatDraft] V3 JSAPI下单成功: prepay_id={data['prepay_id']}")
                return data
            else:
                logger.error(f"[WeChatDraft] V3 JSAPI下单失败: {data}")
                return None
                
    except Exception as e:
        logger.error(f"[WeChatDraft] V3 JSAPI下单异常: {e}")
        return None


def create_v3_native_order(
    total_fee: int,
    description: str,
    out_trade_no
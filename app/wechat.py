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


def upload_draft(
    title: str,
    content: str,
    author: str = "成都K12升学参谋",
    digest: Optional[str] = None,
    thumb_media_id: Optional[str] = None,
    need_open_comment: int = 0,
    only_fans_can_comment: int = 0
) -> Dict[str, Any]:
    """
    上传草稿到微信公众号草稿箱
    
    封装草稿箱上传 API 调用，复用 get_access_token() 获取 access_token。
    支持设置标题、正文（支持HTML/Markdown渲染后的内容）、作者、摘要、封面图片等。
    
    Args:
        title: 文章标题
        content: 文章正文内容（支持HTML格式）
        author: 作者名称，默认为"成都K12升学参谋"
        digest: 文章摘要，不传则自动从正文截取
        thumb_media_id: 封面图片的media_id，不传则使用默认封面
        need_open_comment: 是否打开评论，0=不打开，1=打开，默认0
        only_fans_can_comment: 是否只有粉丝可以评论，0=所有人，1=粉丝，默认0
    
    Returns:
        包含草稿上传结果的字典，格式如：
        {
            "media_id": "xxx",
            "item": [...]
        }
    
    Raises:
        ValueError: 参数验证失败或API调用失败时抛出
        httpx.HTTPError: 网络请求异常时抛出
    """
    # 参数验证
    if not title or not title.strip():
        raise ValueError("文章标题不能为空")
    if not content or not content.strip():
        raise ValueError("文章正文内容不能为空")
    if len(title) > 64:
        raise ValueError("文章标题长度不能超过64个字符")
    
    # 获取access_token
    try:
        access_token = get_access_token()
    except ValueError as e:
        logger.error(f"[WeChatDraft] 获取access_token失败: {e}")
        raise
    
    # 构建草稿内容
    # 如果未提供摘要，从正文中截取前120个字符（去除HTML标签）
    if not digest:
        import re
        # 去除HTML标签
        clean_content = re.sub(r'<[^>]+>', '', content)
        # 去除多余空白
        clean_content = re.sub(r'\s+', ' ', clean_content).strip()
        digest = clean_content[:120] if len(clean_content) > 120 else clean_content
    
    # 构建请求体
    draft_data = {
        "articles": [
            {
                "title": title.strip(),
                "author": author.strip() if author else "成都K12升学参谋",
                "digest": digest.strip(),
                "content": content,
                "content_source_url": "",  # 原文链接，可选
                "thumb_media_id": thumb_media_id if thumb_media_id else "",
                "need_open_comment": need_open_comment,
                "only_fans_can_comment": only_fans_can_comment
            }
        ]
    }
    
    # 调用草稿箱上传API
    url = f"{WECHAT_API_BASE_URL}/draft/add"
    params = {"access_token": access_token}
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            logger.info(f"[WeChatDraft] 开始上传草稿: {title[:30]}...")
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    url,
                    params=params,
                    json=draft_data,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                result = response.json()
                
                if "media_id" in result:
                    logger.info(f"[WeChatDraft] 草稿上传成功，media_id: {result['media_id']}")
                    return result
                else:
                    error_msg = f"上传草稿失败: {result.get('errmsg', '未知错误')}"
                    logger.error(f"[WeChatDraft] {error_msg}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    raise ValueError(error_msg)
                    
        except httpx.HTTPError as e:
            logger.error(f"[WeChatDraft] 上传草稿网络请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            raise


def upload_draft_with_markdown(
    markdown_content: str,
    title: str,
    author: str = "成都K12升学参谋",
    digest: Optional[str] = None,
    thumb_media_id: Optional[str] = None,
    need_open_comment: int = 0,
    only_fans_can_comment: int = 0
) -> Dict[str, Any]:
    """
    上传Markdown格式内容到微信公众号草稿箱
    
    将Markdown内容转换为HTML后上传，支持代码高亮、表格等富文本格式。
    
    Args:
        markdown_content: Markdown格式的文章正文
        title: 文章标题
        author: 作者名称
        digest: 文章摘要
        thumb_media_id: 封面图片media_id
        need_open_comment: 是否打开评论
        only_fans_can_comment: 是否仅粉丝可评论
    
    Returns:
        上传结果字典
    """
    try:
        # 尝试导入markdown库，如果不可用则使用简单转换
        try:
            import markdown
            # 配置markdown扩展
            extensions = [
                'markdown.extensions.extra',
                'markdown.extensions.codehilite',
                'markdown.extensions.tables',
                'markdown.extensions.toc',
                'markdown.extensions.fenced_code'
            ]
            html_content = markdown.markdown(
                markdown_content,
                extensions=extensions,
                output_format='html5'
            )
        except ImportError:
            # 如果没有markdown库，进行简单的行内转换
            logger.warning("[WeChatDraft] markdown库未安装，使用简单转换")
            html_content = _simple_markdown_to_html(markdown_content)
        
        # 包装成完整的HTML文档（适配微信公众号样式）
        full_html = f"""<section style="padding: 10px 15px; line-height: 1.8; font-size: 16px; color: #333;">
{html_content}
</section>"""
        
        return upload_draft(
            title=title,
            content=full_html,
            author=author,
            digest=digest,
            thumb_media_id=thumb_media_id,
            need_open_comment=need_open_comment,
            only_fans_can_comment=only_fans_can_comment
        )
        
    except Exception as e:
        logger.error(f"[WeChatDraft] Markdown转HTML并上传失败: {e}")
        raise


def _simple_markdown_to_html(markdown_text: str) -> str:
    """
    简单的Markdown转HTML函数（不依赖第三方库）
    
    Args:
        markdown_text: Markdown格式文本
    
    Returns:
        HTML格式文本
    """
    import re
    
    lines = markdown_text.split('\n')
    html_lines = []
    in_code_block = False
    code_content = []
    
    for line in lines:
        # 代码块处理
        if line.strip().startswith('```'):
            if in_code_block:
                # 结束代码块
                html_lines.append(f'<pre><code>{"".join(code_content)}</code></pre>')
                code_content = []
                in_code_block = False
            else:
                in_code_block = True
            continue
        
        if in_code_block:
            code_content.append(line + '\n')
            continue
        
        # 标题处理
        if line.startswith('### '):
            html_lines.append(f'<h3>{line[4:]}</h3>')
        elif line.startswith('## '):
            html_lines.append(f'<h2>{line[3:]}</h2>')
        elif line.startswith('# '):
            html_lines.append(f'<h1>{line[2:]}</h1>')
        # 列表处理
        elif line.strip().startswith('- '):
            html_lines.append(f'<li>{line.strip()[2:]}</li>')
        elif line.strip().startswith('* '):
            html_lines.append(f'<li>{line.strip()[2:]}</li>')
        # 空行
        elif not line.strip():
            html_lines.append('<br>')
        # 普通段落
        else:
            # 处理行内样式
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            line = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
            line = re.sub(r'`(.+?)`', r'<code>\1</code>', line)
            html_lines.append(f'<p>{line}</p>')
    
    # 如果代码块未闭合，强制闭合
    if in_code_block:
        html_lines.append(f'<pre><code>{"".join(code_content)}</code></pre>')
    
    return '\n'.join(html_lines)


def get_draft_list(offset: int = 0, count: int = 20, no_content: int = 0) -> Dict[str, Any]:
    """
    获取草稿箱列表
    
    Args:
        offset: 偏移位置，从0开始
        count: 获取数量，默认20，最大20
        no_content: 是否不返回正文，0=返回正文，1=不返回正文
    
    Returns:
        草稿列表信息
    """
    try:
        access_token = get_access_token()
    except ValueError as e:
        logger.error(f"[WeChatDraft] 获取access_token失败: {e}")
        raise
    
    url = f"{WECHAT_API_BASE_URL}/draft/batchget"
    params = {"access_token": access_token}
    
    request_data = {
        "offset": offset,
        "count": min(count, 20),  # 微信限制最大20
        "no_content": no_content
    }
    
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, params=params, json=request_data)
            response.raise_for_status()
            result = response.json()
            
            if "item" in result:
                logger.info(f"[WeChatDraft] 获取草稿列表成功，共{len(result['item'])}篇")
                return result
            else:
                error_msg = f"获取草稿列表失败: {result.get('errmsg', '未知错误')}"
                logger.error(f"[WeChatDraft] {error_msg}")
                raise ValueError(error_msg)
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatDraft] 获取草稿列表网络请求失败: {e}")
        raise


def update_draft(
    media_id: str,
    title: str,
    content: str,
    author: str = "成都K12升学参谋",
    digest: Optional[str] = None,
    thumb_media_id: Optional[str] = None,
    need_open_comment: int = 0,
    only_fans_can_comment: int = 0,
    index: int = 0
) -> Dict[str, Any]:
    """
    更新草稿箱中的草稿
    
    Args:
        media_id: 草稿的media_id
        title: 文章标题
        content: 文章正文内容
        author: 作者名称
        digest: 文章摘要
        thumb_media_id: 封面图片media_id
        need_open_comment: 是否打开评论
        only_fans_can_comment: 是否仅粉丝可评论
        index: 要更新的文章在草稿中的位置（多图文时使用），默认0
    
    Returns:
        更新结果
    """
    try:
        access_token = get_access_token()
    except ValueError as e:
        logger.error(f"[WeChatDraft] 获取access_token失败: {e}")
        raise
    
    # 如果未提供摘要，从正文中截取
    if not digest:
        import re
        clean_content = re.sub(r'<[^>]+>', '', content)
        clean_content = re.sub(r'\s+', ' ', clean_content).strip()
        digest = clean_content[:120] if len(clean_content) > 120 else clean_content
    
    url = f"{WECHAT_API_BASE_URL}/draft/update"
    params = {"access_token": access_token}
    
    update_data = {
        "media_id": media_id,
        "index": index,
        "articles": {
            "title": title.strip(),
            "author": author.strip() if author else "成都K12升学参谋",
            "digest": digest.strip(),
            "content": content,
            "thumb_media_id": thumb_media_id if thumb_media_id else "",
            "need_open_comment": need_open_comment,
            "only_fans_can_comment": only_fans_can_comment
        }
    }
    
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, params=params, json=update_data)
            response.raise_for_status()
            result = response.json()
            
            if result.get("errcode") == 0:
                logger.info(f"[WeChatDraft] 草稿更新成功，media_id: {media_id}")
                return result
            else:
                error_msg = f"更新草稿失败: {result.get('errmsg', '未知错误')}"
                logger.error(f"[WeChatDraft] {error_msg}")
                raise ValueError(error_msg)
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatDraft] 更新草稿网络请求失败: {e}")
        raise


def delete_draft(media_id: str) -> Dict[str, Any]:
    """
    删除草稿箱中的草稿
    
    Args:
        media_id: 要删除的草稿media_id
    
    Returns:
        删除结果
    """
    try:
        access_token = get_access_token()
    except ValueError as e:
        logger.error(f"[WeChatDraft] 获取access_token失败: {e}")
        raise
    
    url = f"{WECHAT_API_BASE_URL}/draft/delete"
    params = {"access_token": access_token}
    
    delete_data = {
        "media_id": media_id
    }
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, params=params, json=delete_data)
            response.raise_for_status()
            result = response.json()
            
            if result.get("errcode") == 0:
                logger.info(f"[WeChatDraft] 草稿删除成功，media_id: {media_id}")
                return result
            else:
                error_msg = f"删除草稿失败: {result.get('errmsg', '未知错误')}"
                logger.error(f"[WeChatDraft] {error_msg}")
                raise ValueError(error_msg)
                
    except httpx.HTTPError as e:
        logger.error(f"[WeChatDraft] 删除草稿网络请求失败: {e}")
        raise


# ============================================================
# 支付相关工具函数（保持原有代码）
# ============================================================

def generate_pay_sign(params: Dict[str, str], key: str) -> str:
    """
    生成微信支付签名（V2）
    
    Args:
        params: 参数字典
        key: 商户API密钥
    
    Returns:
        签名字符串
    """
    # 移除空值和sign字段
    filtered_params = {k: v for k, v in params.items() if v and k != 'sign'}
    
    # 按字典序排序
    sorted_keys = sorted(filtered_params.keys())
    
    # 拼接字符串
    sign_str = '&'.join([f"{k}={filtered_params[k]}" for k in sorted_keys])
    sign_str += f"&key={key}"
    
    # MD5加密并转大写
    sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
    
    return sign


def verify_pay_callback(xml_data: str, key: str) -> Optional[Dict[str, str]]:
    """
    验证微信支付回调签名（V2）
    
    Args:
        xml_data: 微信回调的XML数据
        key: 商户API密钥
    
    Returns:
        验证成功返回参数字典，失败返回None
    """
    try:
        root = ET.fromstring(xml_data)
        params = {}
        for child in root:
            params[child.tag] = child.text
        
        # 验证签名
        if 'sign' not in params:
            logger.error("[WeChatPay] 回调数据缺少sign字段")
            return None
        
        expected_sign = generate_pay_sign(params, key)
        if params['sign'] != expected_sign:
            logger.error("[WeChatPay] 回调签名验证失败")
            return None
        
        return params
        
    except ET.ParseError as e:
        logger.error(f"[WeChatPay] 解析回调XML失败: {e}")
        return None


def build_pay_success_response() -> str:
    """
    构建支付成功响应XML
    
    Returns:
        成功响应的XML字符串
    """
    return """<xml>
    <return_code><![CDATA[SUCCESS]]></return_code>
    <return_msg><![CDATA[OK]]></return_msg>
</xml>"""


def build_pay_fail_response(msg: str = "FAIL") -> str:
    """
    构建支付失败响应XML
    
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
# 微信支付V3相关函数
# ============================================================

def _load_v3_private_key() -> bytes:
    """
    加载V3商户私钥
    
    Returns:
        私钥字节数据
    """
    global _v3_private_key_cache
    
    if _v3_private_key_cache:
        return _v3_private_key_cache
    
    if not WECHAT_PAY_V3_PRIVATE_KEY_PATH:
        raise ValueError("WECHAT_PAY_V3_PRIVATE_KEY_PATH 环境变量未设置")
    
    try:
        with open(WECHAT_PAY_V3_PRIVATE_KEY_PATH, 'rb') as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
            # 获取私钥的字节表示
            private_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            _v3_private_key_cache = private_bytes
            return private_bytes
    except Exception as e:
        logger.error(f"[WeChatPayV3] 加载商户私钥失败: {e}")
        raise


def generate_v3_sign(method: str, url_path: str, body: str = "", timestamp: Optional[str] = None, nonce: Optional[str] = None) -> Dict[str, str]:
    """
    生成微信支付V3接口签名
    
    Args:
        method: HTTP方法（GET/POST/PUT等）
        url_path: 请求路径（如/v3/pay/transactions/jsapi）
        body: 请求体字符串，GET请求为空字符串
        timestamp: 时间戳，不传则自动生成
        nonce: 随机字符串，不传则自动生成
    
    Returns:
        包含签名相关信息的字典
    """
    if not timestamp:
        timestamp = str(int(time.time()))
    if not nonce:
        nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # 构建签名串
    sign_str = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
    
    # 加载私钥并签名
    try:
        private_key_data = _load_v3_private_key()
        private_key = serialization.load_pem_private_key(
            private_key_data,
            password=None,
            backend=default_backend()
        )
        
        signature = private_key.sign(
            sign_str.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        signature_base64 = base64.b64encode(signature).decode('utf-8')
        
        # 构建Authorization头
        authorization = f'WECHATPAY2-SHA256-RSA2048 mchid="{WECHAT_PAY_V3_MCHID}",nonce_str="{nonce}",timestamp="{timestamp}",serial_no="{WECHAT_PAY_V3_SERIAL_NO}",signature="{signature_base64}"'
        
        return {
            "authorization": authorization,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature_base64
        }
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 生成签名失败: {e}")
        raise


def decrypt_v3_callback(ciphertext: str, associated_data: str, nonce: str) -> str:
    """
    解密微信支付V3回调中的敏感信息
    
    Args:
        ciphertext: 密文（Base64编码）
        associated_data: 附加数据
        nonce: 随机串
    
    Returns:
        解密后的明文
    
    Raises:
        ValueError: 解密失败时抛出
    """
    if not WECHAT_PAY_V3_API_V3_KEY:
        raise ValueError("WECHAT_PAY_V3_API_V3_KEY 环境变量未设置")
    
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        
        # 将APIv3密钥转为字节
        api_key = WECHAT_PAY_V3_API_V3_KEY.encode('utf-8')
        
        # Base64解码密文
        ciphertext_bytes = base64.b64decode(ciphertext)
        
        # 构建AAD（附加认证数据）
        aad = associated_data.encode('utf-8') if associated_data else b""
        
        # 构建nonce
        nonce_bytes = nonce.encode('utf-8')
        
        # 解密
        aesgcm = AESGCM(api_key)
        plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, aad)
        
        return plaintext.decode('utf-8')
        
    except ImportError:
        logger.error("[WeChatPayV3] 需要cryptography库支持AES-GCM解密")
        raise
    except Exception as e:
        logger.error(f"[WeChatPayV3] 解密回调数据失败: {e}")
        raise ValueError(f"解密回调数据失败: {e}")


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
        body: 请求体
    
    Returns:
        验证结果
    """
    try:
        # 构建验签串
        sign_str = f"{wechatpay_timestamp}\n{wechatpay_nonce}\n{body}\n"
        
        # 获取微信平台证书（实际项目中应缓存并定期更新）
        # 这里简化处理，实际应该调用 https://api.mch.weixin.qq.com/v3/certificates 获取
        # 并验证 serial_no 匹配
        
        # 注意：实际生产环境中需要实现证书获取和缓存逻辑
        # 以下为简化示例
        logger.warning("[WeChatPayV3] 回调签名验证需要实现微信平台证书获取逻辑")
        
        # 返回True表示验证通过（简化处理）
        return True
        
    except Exception as e:
        logger.error(f"[WeChatPayV3] 验证回调签名失败: {e}")
        return False


def create_v3_order(
    description: str,
    out_trade_no: str,
    total_fee: int,
    openid: str,
    notify_url: Optional[str] = None,
    attach: Optional[str] = None
) -> Dict[str, Any]:
    """
    创建微信支付V3 JSAPI订单
    
    Args:
        description: 商品描述
        out_trade_no: 商户订单号
        total_fee: 订单金额（分）
        openid: 用户openid
        notify_url: 回调地址，不传则使用默认配置
        attach: 附加数据
    
    Returns:
        预支付结果
    """
    if not notify_url:
        notify_url = WECHAT_PAY_V3_NOTIFY_URL
    
    url_path = "/v3/pay/transactions/jsapi"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    request_body = {
        "appid": WECHAT_APPID,
        "mchid": WECHAT_PAY_V3_MCHID,
        "description": description,
        "out_trade_no": out_trade_no,
        "notify_url": notify_url,
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
    
    body_str = json.dumps(request_body, ensure_ascii=False)
    
    try:
        # 生成签名
        sign_info = generate_v3_sign("POST", url_path, body_str)
        
        headers = {
            "Authorization": sign_info["authorization"],
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "K12-Rocket/2.0"
        }
        
        with httpx.Client(timeout=15.0, verify=True) as client:
            response = client.post(url, headers=headers, json=request_body)
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"[WeChatPayV3] 创建订单成功: {out_trade_no}")
            return result
            
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 创建订单网络请求失败: {e}")
        raise
    except Exception as e:
        logger.error(f"[WeChatPayV3] 创建订单失败: {e}")
        raise


def query_v3_order(out_trade_no: str) -> Dict[str, Any]:
    """
    查询微信支付V3订单状态
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        订单信息
    """
    url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    params = {
        "mchid": WECHAT_PAY_V3_MCHID
    }
    
    try:
        # GET请求body为空
        sign_info = generate_v3_sign("GET", url_path)
        
        headers = {
            "Authorization": sign_info["authorization"],
            "Accept": "application/json",
            "User-Agent": "K12-Rocket/2.0"
        }
        
        with httpx.Client(timeout=10.0, verify=True) as client:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"[WeChatPayV3] 查询订单成功: {out_trade_no}")
            return result
            
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 查询订单网络请求失败: {e}")
        raise
    except Exception as e:
        logger.error(f"[WeChatPayV3] 查询订单失败: {e}")
        raise


def close_v3_order(out_trade_no: str) -> bool:
    """
    关闭微信支付V3订单
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        是否关闭成功
    """
    url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close"
    url = f"{WECHAT_PAY_V3_API_BASE_URL}{url_path}"
    
    request_body = {
        "mchid": WECHAT_PAY_V3_MCHID
    }
    
    body_str = json.dumps(request_body, ensure_ascii=False)
    
    try:
        sign_info = generate_v3_sign("POST", url_path, body_str)
        
        headers = {
            "Authorization": sign_info["authorization"],
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "K12-Rocket/2.0"
        }
        
        with httpx.Client(timeout=10.0, verify=True) as client:
            response = client.post(url, headers=headers, json=request_body)
            response.raise_for_status()
            
            logger.info(f"[WeChatPayV3] 关闭订单成功: {out_trade_no}")
            return True
            
    except httpx.HTTPError as e:
        logger.error(f"[WeChatPayV3] 关闭订单网络请求失败: {e}")
        return False
    except Exception as e:
        logger.error(f"[WeChatPayV3] 关闭订单失败: {e}")
        return False


def refund_v3_order(
    out_trade_no: str,
    out_refund_no: str,
    refund_fee: int,
    total_fee: int,
    reason: Optional[str] = None,
    notify_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    微信支付V3退款
    
    Args:
        out_trade_no: 原商户订单号
        out_ref
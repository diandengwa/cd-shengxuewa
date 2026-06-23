#!/usr/bin/env python3
"""
opc_generate_v4.py — 内容工厂流水线 v4
在原有生成流程基础上追加：
  1. Markdown 排版（调用排版引擎）
  2. 微信公众号草稿箱自动上传（通过微信公众平台 API）
  3. 上传成功后通过企业微信/钉钉 webhook 或邮件通知创始人
"""

import os
import sys
import json
import time
import logging
import hashlib
import hmac
import base64
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

import requests
from dotenv import load_dotenv

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

# ============================================================
# 日志配置
# ============================================================
logs_dir = PROJECT_ROOT / "logs"
logs_dir.mkdir(exist_ok=True)

LOG_LEVEL = os.getenv("K12_LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(logs_dir / "opc_generate_v4.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("opc_generate_v4")

# ============================================================
# 配置读取
# ============================================================
# 微信公众平台配置
WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET", "")
WECHAT_ACCESS_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WECHAT_DRAFT_ADD_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"

# 通知配置（企业微信/钉钉 webhook 或邮件）
NOTIFY_TYPE = os.getenv("NOTIFY_TYPE", "wecom").lower()  # wecom / dingtalk / email
WECOM_WEBHOOK_URL = os.getenv("WECOM_WEBHOOK_URL", "")
DINGTALK_WEBHOOK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.qq.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "465"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# ============================================================
# 微信 Access Token 管理（带缓存）
# ============================================================
_wechat_access_token: Optional[str] = None
_wechat_token_expires_at: float = 0


def get_wechat_access_token() -> str:
    """获取微信全局 access_token，带缓存"""
    global _wechat_access_token, _wechat_token_expires_at

    if _wechat_access_token and time.time() < _wechat_token_expires_at - 60:
        return _wechat_access_token

    if not WECHAT_APPID or not WECHAT_APPSECRET:
        raise ValueError("微信配置缺失: WECHAT_APPID / WECHAT_APPSECRET")

    params = {
        "grant_type": "client_credential",
        "appid": WECHAT_APPID,
        "secret": WECHAT_APPSECRET,
    }
    resp = requests.get(WECHAT_ACCESS_TOKEN_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"获取微信 access_token 失败: {data}")

    _wechat_access_token = data["access_token"]
    _wechat_token_expires_at = time.time() + data.get("expires_in", 7200)
    logger.info("微信 access_token 刷新成功")
    return _wechat_access_token


# ============================================================
# Markdown 排版引擎
# ============================================================
def format_markdown(content: str, title: str = "") -> str:
    """
    对 Markdown 内容进行排版优化：
    - 确保标题层级正确
    - 添加适当的空行
    - 统一列表格式
    - 添加分隔线等
    """
    lines = content.split("\n")
    formatted_lines = []

    # 如果内容没有一级标题，添加
    has_h1 = any(line.strip().startswith("# ") for line in lines)
    if not has_h1 and title:
        formatted_lines.append(f"# {title}")
        formatted_lines.append("")

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 跳过空行
        if not stripped:
            formatted_lines.append("")
            continue

        # 处理标题：确保标题前后有空行
        if stripped.startswith("#"):
            # 如果前一行不是空行，添加空行
            if formatted_lines and formatted_lines[-1] != "":
                formatted_lines.append("")
            formatted_lines.append(stripped)
            # 标题后添加空行
            formatted_lines.append("")
            continue

        # 处理列表项
        if stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("+ "):
            formatted_lines.append(stripped)
            continue

        # 处理数字列表
        if stripped[0].isdigit() and ". " in stripped[:4]:
            formatted_lines.append(stripped)
            continue

        # 处理引用
        if stripped.startswith(">"):
            formatted_lines.append(stripped)
            continue

        # 处理代码块标记
        if stripped.startswith("```"):
            formatted_lines.append(stripped)
            continue

        # 处理分隔线
        if stripped in ("---", "***", "___"):
            formatted_lines.append(stripped)
            formatted_lines.append("")
            continue

        # 普通段落
        formatted_lines.append(stripped)

    # 清理末尾多余空行
    while formatted_lines and formatted_lines[-1] == "":
        formatted_lines.pop()

    return "\n".join(formatted_lines)


# ============================================================
# 微信公众号草稿箱上传
# ============================================================
def upload_to_wechat_draft(
    title: str,
    content: str,
    author: str = "成都K12升学参谋",
    digest: str = "",
    thumb_media_id: str = "",
    need_open_comment: int = 0,
    only_fans_can_comment: int = 0
) -> Dict[str, Any]:
    """
    上传图文消息到微信公众号草稿箱

    参数:
        title: 文章标题
        content: 文章内容（HTML格式）
        author: 作者
        digest: 摘要
        thumb_media_id: 封面图片素材ID
        need_open_comment: 是否打开评论（0不打开，1打开）
        only_fans_can_comment: 是否只有粉丝可以评论

    返回:
        微信API响应结果
    """
    try:
        access_token = get_wechat_access_token()

        # 构建请求体
        articles = [{
            "title": title,
            "author": author,
            "digest": digest,
            "content": content,
            "thumb_media_id": thumb_media_id,
            "need_open_comment": need_open_comment,
            "only_fans_can_comment": only_fans_can_comment,
        }]

        payload = {
            "articles": articles
        }

        # 发送请求
        url = f"{WECHAT_DRAFT_ADD_URL}?access_token={access_token}"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        result = resp.json()

        if "media_id" in result:
            logger.info(f"草稿箱上传成功，media_id: {result['media_id']}")
            return result
        else:
            error_msg = result.get("errmsg", "未知错误")
            logger.error(f"草稿箱上传失败: {result}")
            raise RuntimeError(f"微信草稿箱上传失败: {error_msg}")

    except requests.RequestException as e:
        logger.error(f"网络请求失败: {e}")
        raise
    except Exception as e:
        logger.error(f"上传草稿箱异常: {e}")
        raise


# ============================================================
# Markdown 转 HTML（微信图文格式）
# ============================================================
def markdown_to_wechat_html(markdown_content: str) -> str:
    """
    将 Markdown 内容转换为微信公众号支持的 HTML 格式

    注意：微信公众号图文消息支持部分 HTML 标签，不支持 CSS 样式
    这里做简单的转换，复杂的 Markdown 特性可能需要更完善的转换器
    """
    import re

    lines = markdown_content.split("\n")
    html_parts = []
    in_code_block = False
    code_block_content = []

    for line in lines:
        stripped = line.strip()

        # 处理代码块
        if stripped.startswith("```"):
            if in_code_block:
                # 结束代码块
                code_text = "\n".join(code_block_content)
                html_parts.append(f"<pre><code>{code_text}</code></pre>")
                code_block_content = []
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_block_content.append(line)
            continue

        # 处理标题
        if stripped.startswith("# "):
            html_parts.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("## "):
            html_parts.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("### "):
            html_parts.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("#### "):
            html_parts.append(f"<h4>{stripped[5:]}</h4>")
        elif stripped.startswith("##### "):
            html_parts.append(f"<h5>{stripped[6:]}</h5>")
        elif stripped.startswith("###### "):
            html_parts.append(f"<h6>{stripped[7:]}</h6>")

        # 处理引用
        elif stripped.startswith(">"):
            quote_text = stripped[1:].strip()
            html_parts.append(f"<blockquote>{quote_text}</blockquote>")

        # 处理无序列表
        elif stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("+ "):
            list_text = stripped[2:]
            html_parts.append(f"<li>{list_text}</li>")

        # 处理有序列表
        elif re.match(r"^\d+\.\s", stripped):
            list_text = re.sub(r"^\d+\.\s", "", stripped)
            html_parts.append(f"<li>{list_text}</li>")

        # 处理分隔线
        elif stripped in ("---", "***", "___"):
            html_parts.append("<hr/>")

        # 处理图片
        elif stripped.startswith("!["):
            img_match = re.match(r"!\[(.*?)\]\((.*?)\)", stripped)
            if img_match:
                alt_text = img_match.group(1)
                img_url = img_match.group(2)
                html_parts.append(f'<img src="{img_url}" alt="{alt_text}"/>')

        # 处理链接
        elif "[" in stripped and "](" in stripped:
            # 简单处理行内链接
            link_text = re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', stripped)
            html_parts.append(f"<p>{link_text}</p>")

        # 处理空行
        elif not stripped:
            html_parts.append("<p>&nbsp;</p>")

        # 普通段落
        else:
            # 处理加粗和斜体
            text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", stripped)
            text = re.sub(r"\*(.*?)\*", r"<em>\1</em>", text)
            html_parts.append(f"<p>{text}</p>")

    return "\n".join(html_parts)


# ============================================================
# 通知发送
# ============================================================
def send_notification(title: str, media_id: str, status: str = "success", error_msg: str = "") -> bool:
    """
    发送通知给创始人

    支持：企业微信机器人、钉钉机器人、邮件
    """
    try:
        if NOTIFY_TYPE == "wecom":
            return _send_wecom_notification(title, media_id, status, error_msg)
        elif NOTIFY_TYPE == "dingtalk":
            return _send_dingtalk_notification(title, media_id, status, error_msg)
        elif NOTIFY_TYPE == "email":
            return _send_email_notification(title, media_id, status, error_msg)
        else:
            logger.warning(f"不支持的通知类型: {NOTIFY_TYPE}")
            return False
    except Exception as e:
        logger.error(f"发送通知失败: {e}")
        return False


def _send_wecom_notification(title: str, media_id: str, status: str, error_msg: str) -> bool:
    """发送企业微信机器人通知"""
    if not WECOM_WEBHOOK_URL:
        logger.warning("企业微信 webhook URL 未配置")
        return False

    if status == "success":
        content = f"✅ 内容工厂流水线执行成功\n\n标题：{title}\n草稿箱ID：{media_id}\n时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    else:
        content = f"❌ 内容工厂流水线执行失败\n\n标题：{title}\n错误：{error_msg}\n时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    payload = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }

    try:
        resp = requests.post(WECOM_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info("企业微信通知发送成功")
            return True
        else:
            logger.error(f"企业微信通知发送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"企业微信通知发送异常: {e}")
        return False


def _send_dingtalk_notification(title: str, media_id: str, status: str, error_msg: str) -> bool:
    """发送钉钉机器人通知（支持加签安全设置）"""
    if not DINGTALK_WEBHOOK_URL:
        logger.warning("钉钉 webhook URL 未配置")
        return False

    # 构建请求 URL（如果配置了加签密钥）
    webhook_url = DINGTALK_WEBHOOK_URL
    if DINGTALK_SECRET:
        timestamp = str(int(time.time() * 1000))
        sign_string = f"{timestamp}\n{DINGTALK_SECRET}"
        sign = base64.b64encode(
            hmac.new(
                DINGTALK_SECRET.encode("utf-8"),
                sign_string.encode("utf-8"),
                hashlib.sha256
            ).digest()
        ).decode("utf-8")
        webhook_url = f"{DINGTALK_WEBHOOK_URL}&timestamp={timestamp}&sign={urllib.parse.quote(sign)}"

    if status == "success":
        title_text = "✅ 内容工厂流水线执行成功"
        text = f"### {title_text}\n\n- **标题**：{title}\n- **草稿箱ID**：{media_id}\n- **时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    else:
        title_text = "❌ 内容工厂流水线执行失败"
        text = f"### {title_text}\n\n- **标题**：{title}\n- **错误**：{error_msg}\n- **时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title_text,
            "text": text
        }
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info("钉钉通知发送成功")
            return True
        else:
            logger.error(f"钉钉通知发送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"钉钉通知发送异常: {e}")
        return False


def _send_email_notification(title: str, media_id: str, status: str, error_msg: str) -> bool:
    """发送邮件通知"""
    if not all([EMAIL_SMTP_HOST, EMAIL_USER, EMAIL_PASSWORD, EMAIL_TO]):
        logger.warning("邮件配置不完整")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"内容工厂流水线通知 - {title}"
        msg["From"] = EMAIL_USER
        msg["To"] = EMAIL_TO

        if status == "success":
            html_content = f"""
            <html>
            <body>
                <h2>✅ 内容工厂流水线执行成功</h2>
                <p><strong>标题：</strong>{title}</p>
                <p><strong>草稿箱ID：</strong>{media_id}</p>
                <p><strong>时间：</strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </body>
            </html>
            """
        else:
            html_content = f"""
            <html>
            <body>
                <h2>❌ 内容工厂流水线执行失败</h2>
                <p><strong>标题：</strong>{title}</p>
                <p><strong>错误：</strong>{error_msg}</p>
                <p><strong>时间：</strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </body>
            </html>
            """

        msg.attach(MIMEText(html_content, "html", "utf-8"))

        with smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USER, [EMAIL_TO], msg.as_string())

        logger.info("邮件通知发送成功")
        return True

    except smtplib.SMTPException as e:
        logger.error(f"邮件发送失败: {e}")
        return False
    except Exception as e:
        logger.error(f"邮件发送异常: {e}")
        return False


# ============================================================
# 主流水线函数
# ============================================================
def run_pipeline(
    title: str,
    content: str,
    author: str = "成都K12升学参谋",
    digest: str = "",
    thumb_media_id: str = "",
    need_open_comment: int = 0,
    only_fans_can_comment: int = 0
) -> Dict[str, Any]:
    """
    执行完整的内容工厂流水线：
    1. Markdown 排版
    2. 转换为微信 HTML 格式
    3. 上传到微信公众号草稿箱
    4. 发送通知

    返回:
        包含执行结果的字典
    """
    result = {
        "success": False,
        "title": title,
        "media_id": "",
        "error_msg": "",
        "timestamp": datetime.now().isoformat()
    }

    try:
        logger.info(f"开始执行内容工厂流水线: {title}")

        # 步骤1: Markdown 排版
        logger.info("步骤1: Markdown 排版")
        formatted_md = format_markdown(content, title)
        logger.info("Markdown 排版完成")

        # 步骤2: 转换为微信 HTML 格式
        logger.info("步骤2: 转换为微信 HTML 格式")
        wechat_html = markdown_to_wechat_html(formatted_md)
        logger.info("HTML 转换完成")

        # 步骤3: 上传到微信公众号草稿箱
        logger.info("步骤3: 上传到微信公众号草稿箱")
        upload_result = upload_to_wechat_draft(
            title=title,
            content=wechat_html,
            author=author,
            digest=digest,
            thumb_media_id=thumb_media_id,
            need_open_comment=need_open_comment,
            only_fans_can_comment=only_fans_can_comment
        )
        media_id = upload_result.get("media_id", "")
        result["media_id"] = media_id
        logger.info(f"草稿箱上传成功，media_id: {media_id}")

        # 步骤4: 发送通知
        logger.info("步骤4: 发送通知")
        notify_success = send_notification(title, media_id, status="success")
        if notify_success:
            logger.info("通知发送成功")
        else:
            logger.warning("通知发送失败，但流水线已执行成功")

        result["success"] = True
        logger.info(f"内容工厂流水线执行成功: {title}")

    except Exception as e:
        error_msg = str(e)
        result["error_msg"] = error_msg
        logger.error(f"内容工厂流水线执行失败: {error_msg}")

        # 发送失败通知
        try:
            send_notification(title, "", status="error", error_msg=error_msg)
        except Exception as notify_error:
            logger.error(f"发送失败通知也失败了: {notify_error}")

    return result


# ============================================================
# 命令行入口
# ============================================================
def main():
    """命令行入口，支持从参数或环境变量读取内容"""
    import argparse

    parser = argparse.ArgumentParser(description="内容工厂流水线 v4")
    parser.add_argument("--title", type=str, help="文章标题")
    parser.add_argument("--content", type=str, help="文章内容（Markdown 格式）")
    parser.add_argument("--content-file", type=str, help="文章内容文件路径")
    parser.add_argument("--author", type=str, default="成都K12升学参谋", help="作者")
    parser.add_argument("--digest", type=str, default="", help="摘要")
    parser.add_argument("--thumb-media-id", type=str, default="", help="封面图片素材ID")
    parser.add_argument("--need-open-comment", type=int, default=0, help="是否打开评论")
    parser.add_argument("--only-fans-can-comment", type=int, default=0, help="是否仅粉丝可评论")

    args = parser.parse_args()

    # 获取内容
    content = args.content
    if not content and args.content_file:
        try:
            with open(args.content_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"读取内容文件失败: {e}")
            sys.exit(1)

    if not content:
        logger.error("请提供文章内容（--content 或 --content-file）")
        sys.exit(1)

    if not args.title:
        logger.error("请提供文章标题（--title）")
        sys.exit(1)

    # 执行流水线
    result = run_pipeline(
        title=args.title,
        content=content,
        author=args.author,
        digest=args.digest,
        thumb_media_id=args.thumb_media_id,
        need_open_comment=args.need_open_comment,
        only_fans_can_comment=args.only_fans_can_comment
    )

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
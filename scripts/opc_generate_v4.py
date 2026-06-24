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
# Markdown 转微信公众号 HTML
# ============================================================
def md_to_wechat_html(md_content: str, title: str = "") -> str:
    """
    将 Markdown 内容转换为微信公众号支持的 HTML 格式
    """
    # 先进行排版优化
    formatted_md = format_markdown(md_content, title)

    lines = formatted_md.split("\n")
    html_parts = []
    in_code_block = False
    code_content = []

    for line in lines:
        stripped = line.strip()

        # 处理代码块
        if stripped.startswith("```"):
            if in_code_block:
                # 结束代码块
                code_html = "<pre><code>" + "\n".join(code_content) + "</code></pre>"
                html_parts.append(code_html)
                code_content = []
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_content.append(stripped)
            continue

        # 跳过空行
        if not stripped:
            html_parts.append("<p><br/></p>")
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
            html_parts.append(f"<blockquote><p>{quote_text}</p></blockquote>")

        # 处理无序列表
        elif stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("+ "):
            list_text = stripped[2:]
            html_parts.append(f"<ul><li>{list_text}</li></ul>")

        # 处理有序列表
        elif stripped[0].isdigit() and ". " in stripped[:4]:
            dot_index = stripped.index(". ")
            list_text = stripped[dot_index + 2:]
            html_parts.append(f"<ol><li>{list_text}</li></ol>")

        # 处理分隔线
        elif stripped in ("---", "***", "___"):
            html_parts.append("<hr/>")

        # 处理图片
        elif stripped.startswith("!["):
            # 提取图片 alt 和 url
            alt_end = stripped.index("]")
            alt = stripped[2:alt_end]
            url_start = stripped.index("(") + 1
            url_end = stripped.index(")")
            url = stripped[url_start:url_end]
            html_parts.append(f'<img src="{url}" alt="{alt}"/>')

        # 处理链接
        elif "[" in stripped and "](" in stripped and stripped.endswith(")"):
            # 简单处理行内链接
            import re
            def replace_link(match):
                text = match.group(1)
                url = match.group(2)
                return f'<a href="{url}">{text}</a>'
            stripped = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, stripped)
            html_parts.append(f"<p>{stripped}</p>")

        # 普通段落
        else:
            # 处理行内样式
            # 加粗
            import re
            stripped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
            # 斜体
            stripped = re.sub(r'\*(.+?)\*', r'<em>\1</em>', stripped)
            # 行内代码
            stripped = re.sub(r'`(.+?)`', r'<code>\1</code>', stripped)
            html_parts.append(f"<p>{stripped}</p>")

    return "\n".join(html_parts)


# ============================================================
# 微信公众号草稿箱上传
# ============================================================
def upload_draft_to_wechat(title: str, html_content: str, author: str = "成都K12升学参谋") -> Dict[str, Any]:
    """
    上传草稿到微信公众号草稿箱
    返回: {"media_id": "xxx"} 或抛出异常
    """
    access_token = get_wechat_access_token()

    # 构建草稿内容
    draft_body = {
        "articles": [
            {
                "title": title,
                "author": author,
                "content": html_content,
                "need_open_comment": 1,
                "only_fans_can_comment": 0,
            }
        ]
    }

    url = f"{WECHAT_DRAFT_ADD_URL}?access_token={access_token}"
    headers = {"Content-Type": "application/json; charset=utf-8"}

    logger.info(f"正在上传草稿: {title}")
    resp = requests.post(url, headers=headers, json=draft_body, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "media_id" not in data:
        error_msg = data.get("errmsg", "未知错误")
        raise RuntimeError(f"上传草稿失败: {error_msg} (errcode: {data.get('errcode', 'N/A')})")

    media_id = data["media_id"]
    logger.info(f"草稿上传成功, media_id: {media_id}")
    return {"media_id": media_id}


# ============================================================
# 通知发送
# ============================================================
def send_notification(title: str, media_id: str, article_url: str = "") -> bool:
    """
    发送通知给创始人，支持企业微信、钉钉、邮件
    返回是否发送成功
    """
    if NOTIFY_TYPE == "wecom":
        return _send_wecom_notification(title, media_id, article_url)
    elif NOTIFY_TYPE == "dingtalk":
        return _send_dingtalk_notification(title, media_id, article_url)
    elif NOTIFY_TYPE == "email":
        return _send_email_notification(title, media_id, article_url)
    else:
        logger.warning(f"未知的通知类型: {NOTIFY_TYPE}")
        return False


def _send_wecom_notification(title: str, media_id: str, article_url: str = "") -> bool:
    """通过企业微信机器人发送通知"""
    if not WECOM_WEBHOOK_URL:
        logger.warning("企业微信 webhook URL 未配置")
        return False

    content = f"📢 内容工厂新文章已生成\n\n标题: {title}\n草稿ID: {media_id}\n"
    if article_url:
        content += f"预览链接: {article_url}\n"
    content += "\n请登录公众号后台确认发布。"

    payload = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }

    try:
        resp = requests.post(WECOM_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("企业微信通知发送成功")
        return True
    except Exception as e:
        logger.error(f"企业微信通知发送失败: {e}")
        return False


def _send_dingtalk_notification(title: str, media_id: str, article_url: str = "") -> bool:
    """通过钉钉机器人发送通知"""
    if not DINGTALK_WEBHOOK_URL:
        logger.warning("钉钉 webhook URL 未配置")
        return False

    # 计算签名（如果配置了 secret）
    timestamp = str(int(time.time() * 1000))
    sign = ""
    if DINGTALK_SECRET:
        string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
        hmac_code = hmac.new(
            DINGTALK_SECRET.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")

    url = DINGTALK_WEBHOOK_URL
    if sign:
        url += f"&timestamp={timestamp}&sign={urllib.parse.quote(sign)}"

    content = f"📢 内容工厂新文章已生成\n\n标题: {title}\n草稿ID: {media_id}\n"
    if article_url:
        content += f"预览链接: {article_url}\n"
    content += "\n请登录公众号后台确认发布。"

    payload = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") == 0:
            logger.info("钉钉通知发送成功")
            return True
        else:
            logger.error(f"钉钉通知发送失败: {data}")
            return False
    except Exception as e:
        logger.error(f"钉钉通知发送失败: {e}")
        return False


def _send_email_notification(title: str, media_id: str, article_url: str = "") -> bool:
    """通过邮件发送通知"""
    if not all([EMAIL_SMTP_HOST, EMAIL_USER, EMAIL_PASSWORD, EMAIL_TO]):
        logger.warning("邮件配置不完整")
        return False

    subject = f"📢 内容工厂新文章: {title}"
    body = f"""
    <h2>内容工厂新文章已生成</h2>
    <p><strong>标题:</strong> {title}</p>
    <p><strong>草稿ID:</strong> {media_id}</p>
    """
    if article_url:
        body += f'<p><strong>预览链接:</strong> <a href="{article_url}">{article_url}</a></p>'
    body += "<p>请登录公众号后台确认发布。</p>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USER, [EMAIL_TO], msg.as_string())
        logger.info("邮件通知发送成功")
        return True
    except Exception as e:
        logger.error(f"邮件通知发送失败: {e}")
        return False


# ============================================================
# 主流程：内容工厂流水线
# ============================================================
def run_content_pipeline(
    markdown_content: str,
    title: str,
    author: str = "成都K12升学参谋",
    notify: bool = True
) -> Dict[str, Any]:
    """
    运行完整的内容工厂流水线：
    1. Markdown 排版
    2. 转换为微信公众号 HTML
    3. 上传草稿箱
    4. 通知创始人

    返回: {
        "success": True/False,
        "media_id": "xxx" (成功时),
        "title": "xxx",
        "notified": True/False
    }
    """
    result = {
        "success": False,
        "media_id": "",
        "title": title,
        "notified": False,
        "error": ""
    }

    try:
        # 步骤1: Markdown 排版
        logger.info(f"开始排版文章: {title}")
        formatted_md = format_markdown(markdown_content, title)
        logger.info("Markdown 排版完成")

        # 步骤2: 转换为微信公众号 HTML
        logger.info("开始转换为微信公众号 HTML")
        html_content = md_to_wechat_html(formatted_md, title)
        logger.info("HTML 转换完成")

        # 步骤3: 上传草稿箱
        logger.info("开始上传草稿箱")
        upload_result = upload_draft_to_wechat(title, html_content, author)
        media_id = upload_result["media_id"]
        result["media_id"] = media_id
        result["success"] = True
        logger.info(f"草稿箱上传成功, media_id: {media_id}")

        # 步骤4: 通知创始人
        if notify:
            logger.info("开始发送通知")
            article_url = f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=10&appmsgid={media_id}&token=&lang=zh_CN"
            notified = send_notification(title, media_id, article_url)
            result["notified"] = notified
            if notified:
                logger.info("通知发送成功")
            else:
                logger.warning("通知发送失败，请检查通知配置")

    except Exception as e:
        error_msg = f"内容工厂流水线执行失败: {str(e)}"
        logger.error(error_msg)
        result["error"] = error_msg
        result["success"] = False

    return result


# ============================================================
# 命令行入口
# ============================================================
def main():
    """命令行入口，支持从文件读取 Markdown 内容"""
    import argparse

    parser = argparse.ArgumentParser(description="内容工厂流水线 v4")
    parser.add_argument("--file", "-f", help="Markdown 文件路径")
    parser.add_argument("--content", "-c", help="Markdown 内容（直接传入）")
    parser.add_argument("--title", "-t", required=True, help="文章标题")
    parser.add_argument("--author", "-a", default="成都K12升学参谋", help="作者名称")
    parser.add_argument("--no-notify", action="store_true", help="不发送通知")

    args = parser.parse_args()

    # 获取 Markdown 内容
    markdown_content = ""
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            logger.error(f"文件不存在: {args.file}")
            sys.exit(1)
        markdown_content = file_path.read_text(encoding="utf-8")
    elif args.content:
        markdown_content = args.content
    else:
        # 从标准输入读取
        logger.info("请粘贴 Markdown 内容（Ctrl+D 结束）:")
        markdown_content = sys.stdin.read()

    if not markdown_content.strip():
        logger.error("Markdown 内容为空")
        sys.exit(1)

    # 运行流水线
    result = run_content_pipeline(
        markdown_content=markdown_content,
        title=args.title,
        author=args.author,
        notify=not args.no_notify
    )

    # 输出结果
    print("\n" + "=" * 50)
    print("内容工厂流水线执行结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("=" * 50)

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
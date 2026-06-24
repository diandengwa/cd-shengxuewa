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
        if stripped.startswith("- ") or stripped.startswith("* "):
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
        if stripped in ["---", "***", "___"]:
            formatted_lines.append("")
            formatted_lines.append(stripped)
            formatted_lines.append("")
            continue

        # 普通段落
        formatted_lines.append(stripped)

    # 清理多余的空行（最多连续两个空行）
    cleaned_lines = []
    empty_count = 0
    for line in formatted_lines:
        if line == "":
            empty_count += 1
            if empty_count <= 2:
                cleaned_lines.append(line)
        else:
            empty_count = 0
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


# ============================================================
# md2wechat 排版函数
# ============================================================
def md2wechat_format(md_content: str, title: str = "") -> str:
    """
    调用 md2wechat 排版引擎进行微信公众号排版
    返回排版后的 HTML 内容（适用于微信公众号编辑器）
    """
    try:
        # 先进行基础 Markdown 排版
        formatted_md = format_markdown(md_content, title)

        # 尝试导入 md2wechat 模块
        try:
            from md2wechat import WeChatRenderer
            renderer = WeChatRenderer()
            html_content = renderer.render(formatted_md)
            logger.info("md2wechat 排版成功")
            return html_content
        except ImportError:
            logger.warning("md2wechat 模块未安装，使用内置简单排版")
            # 内置简单排版：将 Markdown 转换为微信公众号可接受的 HTML
            html_content = simple_md_to_wechat_html(formatted_md)
            return html_content

    except Exception as e:
        logger.error(f"排版失败: {e}")
        # 排版失败时返回原始 Markdown 内容
        return md_content


def simple_md_to_wechat_html(md_content: str) -> str:
    """
    简单的 Markdown 转微信公众号 HTML
    当 md2wechat 模块不可用时使用
    """
    lines = md_content.split("\n")
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

        # 处理标题
        if stripped.startswith("# "):
            html_parts.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("## "):
            html_parts.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("### "):
            html_parts.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("#### "):
            html_parts.append(f"<h4>{stripped[5:]}</h4>")
        # 处理列表
        elif stripped.startswith("- ") or stripped.startswith("* "):
            html_parts.append(f"<li>{stripped[2:]}</li>")
        # 处理引用
        elif stripped.startswith(">"):
            html_parts.append(f"<blockquote>{stripped[1:]}</blockquote>")
        # 处理分隔线
        elif stripped in ["---", "***", "___"]:
            html_parts.append("<hr/>")
        # 处理空行
        elif stripped == "":
            html_parts.append("<p>&nbsp;</p>")
        # 普通段落
        else:
            html_parts.append(f"<p>{stripped}</p>")

    return "\n".join(html_parts)


# ============================================================
# 微信公众号草稿箱上传
# ============================================================
def upload_draft_to_wechat(title: str, content: str, author: str = "成都K12升学参谋") -> Dict[str, Any]:
    """
    上传文章到微信公众号草稿箱
    返回上传结果，包含 media_id
    """
    try:
        access_token = get_wechat_access_token()

        # 构建草稿内容
        draft_data = {
            "articles": [
                {
                    "title": title,
                    "author": author,
                    "content": content,
                    "thumb_media_id": get_thumb_media_id(),
                    "need_open_comment": 1,
                    "only_fans_can_comment": 0,
                }
            ]
        }

        # 调用微信草稿箱 API
        url = f"{WECHAT_DRAFT_ADD_URL}?access_token={access_token}"
        resp = requests.post(url, json=draft_data, timeout=30)
        resp.raise_for_status()
        result = resp.json()

        if "media_id" in result:
            logger.info(f"草稿上传成功，media_id: {result['media_id']}")
            return {
                "success": True,
                "media_id": result["media_id"],
                "title": title,
                "upload_time": datetime.now().isoformat()
            }
        else:
            error_msg = result.get("errmsg", "未知错误")
            logger.error(f"草稿上传失败: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "title": title
            }

    except Exception as e:
        logger.error(f"上传草稿箱异常: {e}")
        return {
            "success": False,
            "error": str(e),
            "title": title
        }


def get_thumb_media_id() -> str:
    """
    获取默认的封面图片 media_id
    可以从环境变量读取，或者使用默认值
    """
    default_thumb = os.getenv("WECHAT_THUMB_MEDIA_ID", "")
    if default_thumb:
        return default_thumb

    # 如果没有配置默认封面，尝试从素材库获取
    try:
        access_token = get_wechat_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/material/batchget_material?access_token={access_token}"
        data = {
            "type": "image",
            "offset": 0,
            "count": 1
        }
        resp = requests.post(url, json=data, timeout=10)
        resp.raise_for_status()
        result = resp.json()

        if result.get("item") and len(result["item"]) > 0:
            return result["item"][0]["media_id"]
    except Exception as e:
        logger.warning(f"获取封面图片失败: {e}")

    # 返回空字符串，微信 API 会使用默认封面
    return ""


# ============================================================
# 通知发送
# ============================================================
def send_notification(title: str, media_id: str, status: str = "success") -> bool:
    """
    发送通知给创始人
    支持企业微信、钉钉、邮件三种方式
    """
    if NOTIFY_TYPE == "wecom":
        return send_wecom_notification(title, media_id, status)
    elif NOTIFY_TYPE == "dingtalk":
        return send_dingtalk_notification(title, media_id, status)
    elif NOTIFY_TYPE == "email":
        return send_email_notification(title, media_id, status)
    else:
        logger.warning(f"不支持的通知类型: {NOTIFY_TYPE}")
        return False


def send_wecom_notification(title: str, media_id: str, status: str) -> bool:
    """通过企业微信 webhook 发送通知"""
    if not WECOM_WEBHOOK_URL:
        logger.warning("企业微信 webhook URL 未配置")
        return False

    try:
        if status == "success":
            content = f"✅ 内容工厂新文章已生成并上传草稿箱\n\n标题：{title}\nmedia_id：{media_id}\n\n请登录公众号后台确认发布。"
        else:
            content = f"❌ 内容工厂文章上传失败\n\n标题：{title}\n错误信息：{media_id}"

        data = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }

        resp = requests.post(WECOM_WEBHOOK_URL, json=data, timeout=10)
        resp.raise_for_status()
        logger.info("企业微信通知发送成功")
        return True

    except Exception as e:
        logger.error(f"企业微信通知发送失败: {e}")
        return False


def send_dingtalk_notification(title: str, media_id: str, status: str) -> bool:
    """通过钉钉 webhook 发送通知"""
    if not DINGTALK_WEBHOOK_URL:
        logger.warning("钉钉 webhook URL 未配置")
        return False

    try:
        # 计算签名（如果配置了 secret）
        timestamp = str(round(time.time() * 1000))
        sign = ""
        if DINGTALK_SECRET:
            string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
            hmac_code = hmac.new(
                DINGTALK_SECRET.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256
            ).digest()
            sign = base64.b64encode(hmac_code).decode("utf-8")

        # 构建 webhook URL
        webhook_url = DINGTALK_WEBHOOK_URL
        if sign:
            webhook_url += f"&timestamp={timestamp}&sign={sign}"

        if status == "success":
            content = f"✅ 内容工厂新文章已生成并上传草稿箱\n\n标题：{title}\nmedia_id：{media_id}\n\n请登录公众号后台确认发布。"
        else:
            content = f"❌ 内容工厂文章上传失败\n\n标题：{title}\n错误信息：{media_id}"

        data = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }

        resp = requests.post(webhook_url, json=data, timeout=10)
        resp.raise_for_status()
        logger.info("钉钉通知发送成功")
        return True

    except Exception as e:
        logger.error(f"钉钉通知发送失败: {e}")
        return False


def send_email_notification(title: str, media_id: str, status: str) -> bool:
    """通过邮件发送通知"""
    if not all([EMAIL_SMTP_HOST, EMAIL_USER, EMAIL_PASSWORD, EMAIL_TO]):
        logger.warning("邮件配置不完整")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"内容工厂文章{'上传成功' if status == 'success' else '上传失败'}"
        msg["From"] = EMAIL_USER
        msg["To"] = EMAIL_TO

        if status == "success":
            text_content = f"""
            内容工厂新文章已生成并上传草稿箱

            标题：{title}
            media_id：{media_id}

            请登录公众号后台确认发布。
            """
        else:
            text_content = f"""
            内容工厂文章上传失败

            标题：{title}
            错误信息：{media_id}

            请检查系统日志。
            """

        msg.attach(MIMEText(text_content, "plain", "utf-8"))

        # 发送邮件
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
def process_content_pipeline(
    title: str,
    md_content: str,
    author: str = "成都K12升学参谋",
    output_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    内容工厂流水线主流程
    1. 生成 Markdown 文件
    2. 排版优化
    3. 上传微信公众号草稿箱
    4. 发送通知
    """
    result = {
        "title": title,
        "timestamp": datetime.now().isoformat(),
        "steps": []
    }

    # 步骤1：生成 Markdown 文件
    logger.info(f"开始处理文章: {title}")
    if output_dir is None:
        output_dir = PROJECT_ROOT / "output" / "articles"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 生成文件名（使用时间戳和标题）
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip()
    safe_title = safe_title.replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_filename = f"{timestamp}_{safe_title}.md"
    md_filepath = output_dir / md_filename

    # 写入 Markdown 文件
    with open(md_filepath, "w", encoding="utf-8") as f:
        f.write(md_content)
    logger.info(f"Markdown 文件已生成: {md_filepath}")
    result["steps"].append({
        "step": "generate_md",
        "status": "success",
        "filepath": str(md_filepath)
    })

    # 步骤2：排版优化
    logger.info("开始排版优化")
    try:
        formatted_content = md2wechat_format(md_content, title)
        # 保存排版后的 HTML 文件
        html_filename = f"{timestamp}_{safe_title}.html"
        html_filepath = output_dir / html_filename
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(formatted_content)
        logger.info(f"排版后的 HTML 文件已生成: {html_filepath}")
        result["steps"].append({
            "step": "format_markdown",
            "status": "success",
            "filepath": str(html_filepath)
        })
    except Exception as e:
        logger.error(f"排版优化失败: {e}")
        result["steps"].append({
            "step": "format_markdown",
            "status": "failed",
            "error": str(e)
        })
        formatted_content = md_content

    # 步骤3：上传微信公众号草稿箱
    logger.info("开始上传微信公众号草稿箱")
    try:
        upload_result = upload_draft_to_wechat(title, formatted_content, author)
        result["steps"].append({
            "step": "upload_draft",
            "status": "success" if upload_result["success"] else "failed",
            "media_id": upload_result.get("media_id", ""),
            "error": upload_result.get("error", "")
        })

        if upload_result["success"]:
            # 步骤4：发送通知
            logger.info("上传成功，发送通知")
            notify_success = send_notification(
                title,
                upload_result["media_id"],
                "success"
            )
            result["steps"].append({
                "step": "notify",
                "status": "success" if notify_success else "failed"
            })
            result["success"] = True
        else:
            # 上传失败，发送失败通知
            logger.error("上传失败，发送失败通知")
            send_notification(title, upload_result.get("error", "未知错误"), "failed")
            result["success"] = False

    except Exception as e:
        logger.error(f"上传流程异常: {e}")
        result["steps"].append({
            "step": "upload_draft",
            "status": "failed",
            "error": str(e)
        })
        # 发送失败通知
        send_notification(title, str(e), "failed")
        result["success"] = False

    return result


# ============================================================
# 命令行入口
# ============================================================
def main():
    """命令行入口函数"""
    import argparse

    parser = argparse.ArgumentParser(description="内容工厂流水线 v4")
    parser.add_argument("--title", required=True, help="文章标题")
    parser.add_argument("--content", help="文章内容（Markdown 格式）")
    parser.add_argument("--content-file", help="文章内容文件路径")
    parser.add_argument("--author", default="成都K12升学参谋", help="作者名称")
    parser.add_argument("--output-dir", help="输出目录")

    args = parser.parse_args()

    # 获取文章内容
    if args.content:
        md_content = args.content
    elif args.content_file:
        with open(args.content_file, "r", encoding="utf-8") as f:
            md_content = f.read()
    else:
        logger.error("请提供文章内容（--content 或 --content-file）")
        sys.exit(1)

    # 执行流水线
    result = process_content_pipeline(
        title=args.title,
        md_content=md_content,
        author=args.author,
        output_dir=Path(args.output_dir) if args.output_dir else None
    )

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("success"):
        logger.info("内容工厂流水线执行成功")
    else:
        logger.error("内容工厂流水线执行失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
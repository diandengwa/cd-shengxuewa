#!/usr/bin/env python3
"""
微信公众号草稿箱上传工具
用于将HTML内容转换为微信图文素材并上传至草稿箱
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional

# 添加项目根目录到系统路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# 导入微信API工具
from app.wechat import get_access_token

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def read_html_content(html_path: str) -> str:
    """
    读取HTML文件内容
    
    Args:
        html_path: HTML文件路径
        
    Returns:
        str: HTML内容字符串
        
    Raises:
        FileNotFoundError: 文件不存在
        IOError: 文件读取失败
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        logger.info(f"成功读取HTML文件: {html_path}")
        return content
    except FileNotFoundError:
        logger.error(f"HTML文件不存在: {html_path}")
        raise
    except Exception as e:
        logger.error(f"读取HTML文件失败: {e}")
        raise


def upload_cover_image(cover_image_path: str) -> Optional[str]:
    """
    上传封面图片到微信素材库
    
    Args:
        cover_image_path: 封面图片路径
        
    Returns:
        Optional[str]: 成功返回media_id，失败返回None
    """
    import httpx
    
    if not os.path.exists(cover_image_path):
        logger.warning(f"封面图片文件不存在: {cover_image_path}")
        return None
    
    try:
        access_token = get_access_token()
        upload_url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"
        
        with open(cover_image_path, 'rb') as f:
            files = {'media': (os.path.basename(cover_image_path), f, 'image/jpeg')}
            with httpx.Client(timeout=30.0) as client:
                response = client.post(upload_url, files=files)
                result = response.json()
                
                if 'media_id' in result:
                    media_id = result['media_id']
                    logger.info(f"封面图片上传成功，media_id: {media_id}")
                    return media_id
                else:
                    logger.error(f"封面图片上传失败: {result.get('errmsg', '未知错误')}")
                    return None
    except Exception as e:
        logger.error(f"封面图片上传异常: {e}")
        return None


def upload_draft(
    html_path: str,
    title: str,
    cover_image_path: Optional[str] = None,
    author: str = "成都K12升学参谋",
    digest: Optional[str] = None,
    content_source_url: Optional[str] = None,
    need_open_comment: int = 0,
    only_fans_can_comment: int = 0
) -> str:
    """
    上传图文素材到微信公众号草稿箱
    
    Args:
        html_path: HTML文件路径
        title: 文章标题
        cover_image_path: 封面图片路径（可选）
        author: 作者名称
        digest: 摘要（可选）
        content_source_url: 原文链接（可选）
        need_open_comment: 是否打开评论（0不打开，1打开）
        only_fans_can_comment: 是否只有粉丝可以评论（0所有人，1粉丝）
        
    Returns:
        str: 草稿箱media_id
        
    Raises:
        Exception: 上传失败时抛出异常
    """
    import httpx
    
    # 读取HTML内容
    html_content = read_html_content(html_path)
    
    # 处理封面图片
    thumb_media_id = None
    if cover_image_path:
        thumb_media_id = upload_cover_image(cover_image_path)
    
    # 构建图文素材
    articles = [{
        "title": title,
        "author": author,
        "digest": digest or "",
        "content": html_content,
        "content_source_url": content_source_url or "",
        "thumb_media_id": thumb_media_id or "",
        "need_open_comment": need_open_comment,
        "only_fans_can_comment": only_fans_can_comment
    }]
    
    # 调用微信草稿箱API
    try:
        access_token = get_access_token()
        draft_url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
        
        draft_data = {
            "articles": articles
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(draft_url, json=draft_data)
            result = response.json()
            
            if 'media_id' in result:
                media_id = result['media_id']
                logger.info(f"草稿箱上传成功，media_id: {media_id}")
                return media_id
            else:
                error_msg = result.get('errmsg', '未知错误')
                error_code = result.get('errcode', -1)
                logger.error(f"草稿箱上传失败 [错误码:{error_code}]: {error_msg}")
                raise Exception(f"草稿箱上传失败: {error_msg}")
                
    except httpx.TimeoutException:
        logger.error("请求微信API超时")
        raise Exception("请求微信API超时，请检查网络连接")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP请求失败: {e}")
        raise Exception(f"HTTP请求失败: {e}")
    except Exception as e:
        logger.error(f"草稿箱上传异常: {e}")
        raise


def main():
    """
    命令行入口函数
    支持通过命令行参数或环境变量配置上传参数
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="微信公众号草稿箱上传工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 基本用法
  python scripts/upload_draft.py --html ./output/article.html --title "文章标题"
  
  # 完整参数
  python scripts/upload_draft.py \\
    --html ./output/article.html \\
    --title "文章标题" \\
    --cover ./images/cover.jpg \\
    --author "成都K12升学参谋" \\
    --digest "文章摘要" \\
    --source-url "https://example.com/article" \\
    --enable-comment
        """
    )
    
    parser.add_argument('--html', required=True, help='HTML文件路径')
    parser.add_argument('--title', required=True, help='文章标题')
    parser.add_argument('--cover', help='封面图片路径')
    parser.add_argument('--author', default='成都K12升学参谋', help='作者名称')
    parser.add_argument('--digest', help='文章摘要')
    parser.add_argument('--source-url', help='原文链接')
    parser.add_argument('--enable-comment', action='store_true', help='启用评论')
    parser.add_argument('--fans-only-comment', action='store_true', help='仅粉丝可评论')
    
    args = parser.parse_args()
    
    # 检查HTML文件是否存在
    if not os.path.exists(args.html):
        logger.error(f"HTML文件不存在: {args.html}")
        sys.exit(1)
    
    # 检查封面图片是否存在（如果指定了）
    if args.cover and not os.path.exists(args.cover):
        logger.warning(f"封面图片不存在: {args.cover}，将跳过封面上传")
        args.cover = None
    
    try:
        # 执行上传
        media_id = upload_draft(
            html_path=args.html,
            title=args.title,
            cover_image_path=args.cover,
            author=args.author,
            digest=args.digest,
            content_source_url=args.source_url,
            need_open_comment=1 if args.enable_comment else 0,
            only_fans_can_comment=1 if args.fans_only_comment else 0
        )
        
        # 输出结果
        result = {
            "success": True,
            "media_id": media_id,
            "title": args.title
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
    except Exception as e:
        logger.error(f"上传失败: {e}")
        result = {
            "success": False,
            "error": str(e)
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
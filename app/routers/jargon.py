#!/usr/bin/env python3
"""
黑话翻译API路由 — 将升学术语翻译为通俗语言
速率限制: 60次/小时
"""

import os
import sys
import json
import logging
import hashlib
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from fastapi import APIRouter, HTTPException, Query, Request, Depends
from pydantic import BaseModel, Field

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ============================================================
# 日志配置
# ============================================================
logger = logging.getLogger("k12.jargon")

# ============================================================
# 黑话翻译数据
# ============================================================
# 升学黑话词典: 术语 -> 通俗解释
JARGON_DICT = {
    "划片": "根据学生户籍所在地，由教育部门统一划分到对应学区学校就读的方式",
    "多校划片": "一个小区对应多所小学/初中，通过电脑随机派位方式确定录取学校",
    "单校划片": "一个小区只对应一所小学/初中，户籍在该区域的学生直接入学",
    "随机派位": "通过电脑程序随机分配学位，类似抽签方式决定学生去哪所学校",
    "大摇号": "成都市直属学校（如四七九中）面向全市学生的电脑随机录取",
    "小摇号": "区属学校面向本区学生的电脑随机录取",
    "民办摇号": "民办学校报名人数超过招生计划时，通过电脑随机录取",
    "直升": "一贯制学校（如九年一贯制）内部学生直接升入本校初中或高中",
    "指标到校": "重点高中将部分招生名额直接分配到区域内初中学校",
    "市级指标": "成都市直属学校分配到各区的指标到校名额",
    "区级指标": "各区属重点高中分配到本区初中学校的指标到校名额",
    "调招": "调剂招生，指未被第一志愿录取的学生参与其他学校的补录",
    "统招": "统一招生，按中考成绩和志愿统一录取的方式",
    "艺体特长生": "在艺术或体育方面有特长的学生，通过专业测试获得降分录取资格",
    "借读": "学生学籍在A校，实际在B校就读，通常需要缴纳借读费",
    "转学": "学生从一所学校转到另一所学校就读，需办理学籍转移手续",
    "择校": "家长通过非正常途径选择心仪学校，通常涉及择校费",
    "学区房": "位于优质学校招生范围内的房产，入学资格与房产挂钩",
    "学位预警": "教育部门发布某学校学位紧张、可能无法容纳所有学生的预警通知",
    "落户年限": "学生户籍迁入学区需要满足的最低年限要求",
    "六年一学位": "一套房产在六年内只能提供一个小学学位（二胎除外）",
    "五年一学位": "一套房产在五年内只能提供一个初中学位（二胎除外）",
    "随迁子女": "跟随父母在非户籍所在地居住并申请入学的学生",
    "积分入学": "根据父母在当地的居住、社保、纳税等积分情况安排入学",
    "两自一包": "学校自主招聘教师、自主管理、经费包干的新型办学模式",
    "名校集团": "以一所名校为核心，联合多所学校组成的教育联合体",
    "领办": "名校对薄弱学校进行管理输出，由名校校长兼任薄弱学校校长",
    "对口": "小学毕业生直接升入指定初中的对应关系",
    "九年一贯制": "小学和初中一体化办学，学生可直升本校初中",
    "十二年一贯制": "小学、初中、高中一体化办学",
    "K12": "从幼儿园到高中12年基础教育全学段",
    "五朵金花": "成都市五所顶尖小学的俗称（泡桐树小学、成都实验小学、成师附小、盐道街小学、龙江路小学）",
    "四七九": "成都四中（石室中学）、七中（成都七中）、九中（树德中学）的俗称",
    "二圈层": "成都市主城区以外的近郊区县",
    "三圈层": "成都市远郊区县",
    "零诊": "高三第一次模拟考试，通常在高三上学期期末",
    "一诊": "高三第二次模拟考试，通常在高三下学期初",
    "二诊": "高三第三次模拟考试，通常在高考前两个月",
    "三诊": "高考前最后一次模拟考试，通常在高考前一个月",
    "调考": "各区教育局组织的统一考试，用于评估学校教学质量",
    "中考": "初中毕业生学业水平考试，决定高中录取",
    "高考": "全国普通高等学校招生统一考试",
    "小升初": "小学六年级学生升入初中的过程",
    "初升高": "初中三年级学生升入高中的过程",
    "幼升小": "幼儿园大班儿童升入小学的过程",
}

# 同义词映射
SYNONYM_MAP = {
    "四中": "四七九",
    "七中": "四七九",
    "九中": "四七九",
    "石室中学": "四七九",
    "成都七中": "四七九",
    "树德中学": "四七九",
    "泡小": "五朵金花",
    "实小": "五朵金花",
    "成师附小": "五朵金花",
    "盐小": "五朵金花",
    "龙小": "五朵金花",
    "摇号": "随机派位",
    "派位": "随机派位",
    "电脑派位": "随机派位",
    "指标": "指标到校",
    "到校指标": "指标到校",
    "直升生": "直升",
    "一贯制": "九年一贯制",
    "十二年制": "十二年一贯制",
}

# ============================================================
# 速率限制器（内存实现）
# ============================================================
class RateLimiter:
    """简单的内存速率限制器"""
    
    def __init__(self, max_requests: int = 60, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = {}
    
    def _get_key(self, client_ip: str) -> str:
        """生成客户端标识"""
        return hashlib.md5(client_ip.encode()).hexdigest()
    
    def is_allowed(self, client_ip: str) -> bool:
        """检查是否允许请求"""
        key = self._get_key(client_ip)
        now = time.time()
        window_start = now - self.window_seconds
        
        # 清理过期记录
        if key in self.requests:
            self.requests[key] = [t for t in self.requests[key] if t > window_start]
        
        # 检查是否超过限制
        if key in self.requests and len(self.requests[key]) >= self.max_requests:
            return False
        
        # 记录请求
        if key not in self.requests:
            self.requests[key] = []
        self.requests[key].append(now)
        return True
    
    def get_remaining(self, client_ip: str) -> int:
        """获取剩余请求次数"""
        key = self._get_key(client_ip)
        now = time.time()
        window_start = now - self.window_seconds
        
        if key in self.requests:
            self.requests[key] = [t for t in self.requests[key] if t > window_start]
            return max(0, self.max_requests - len(self.requests[key]))
        return self.max_requests
    
    def get_reset_time(self, client_ip: str) -> float:
        """获取速率限制重置时间（秒）"""
        key = self._get_key(client_ip)
        now = time.time()
        
        if key in self.requests and self.requests[key]:
            oldest = min(self.requests[key])
            return max(0, self.window_seconds - (now - oldest))
        return 0


# ============================================================
# 全局速率限制器实例
# ============================================================
rate_limiter = RateLimiter(max_requests=60, window_seconds=3600)


# ============================================================
# Pydantic 模型
# ============================================================
class TranslateRequest(BaseModel):
    """翻译请求模型"""
    text: str = Field(..., min_length=1, max_length=500, description="需要翻译的升学术语")
    
    class Config:
        json_schema_extra = {
            "example": {
                "text": "大摇号"
            }
        }


class TranslateResponse(BaseModel):
    """翻译响应模型"""
    success: bool = Field(..., description="请求是否成功")
    original: str = Field(..., description="原始术语")
    translation: str = Field(..., description="通俗解释")
    source: str = Field(default="dictionary", description="翻译来源（dictionary/synonym/not_found）")
    related_terms: List[str] = Field(default=[], description="相关术语推荐")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "original": "大摇号",
                "translation": "成都市直属学校（如四七九中）面向全市学生的电脑随机录取",
                "source": "dictionary",
                "related_terms": ["小摇号", "随机派位", "民办摇号"]
            }
        }


class BatchTranslateRequest(BaseModel):
    """批量翻译请求模型"""
    texts: List[str] = Field(..., min_length=1, max_length=20, description="需要翻译的术语列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "texts": ["大摇号", "指标到校", "五朵金花"]
            }
        }


class BatchTranslateResponse(BaseModel):
    """批量翻译响应模型"""
    success: bool = Field(..., description="请求是否成功")
    results: List[Dict[str, Any]] = Field(..., description="翻译结果列表")
    total: int = Field(..., description="总翻译数量")
    found: int = Field(..., description="成功翻译数量")
    not_found: int = Field(..., description="未找到翻译数量")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "results": [
                    {
                        "original": "大摇号",
                        "translation": "成都市直属学校（如四七九中）面向全市学生的电脑随机录取",
                        "source": "dictionary"
                    }
                ],
                "total": 1,
                "found": 1,
                "not_found": 0
            }
        }


class GlossaryResponse(BaseModel):
    """术语表响应模型"""
    success: bool = Field(..., description="请求是否成功")
    total: int = Field(..., description="术语总数")
    terms: List[Dict[str, str]] = Field(..., description="术语列表")
    categories: Dict[str, List[str]] = Field(default={}, description="分类术语")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "total": 50,
                "terms": [
                    {"term": "划片", "definition": "根据学生户籍所在地..."}
                ]
            }
        }


class ErrorResponse(BaseModel):
    """错误响应模型"""
    success: bool = Field(default=False, description="请求是否成功")
    error: str = Field(..., description="错误信息")
    detail: Optional[str] = Field(default=None, description="详细错误信息")


# ============================================================
# 辅助函数
# ============================================================
def get_related_terms(term: str) -> List[str]:
    """获取相关术语推荐"""
    related = []
    
    # 基于同义词映射查找相关术语
    for synonym, main_term in SYNONYM_MAP.items():
        if main_term == term or synonym == term:
            related.append(synonym)
            if main_term != term:
                related.append(main_term)
    
    # 基于关键词匹配查找相关术语
    for key in JARGON_DICT.keys():
        if key != term and (key in term or term in key):
            related.append(key)
    
    # 去重并限制数量
    related = list(set(related))
    return related[:5]


def translate_term(term: str) -> Dict[str, Any]:
    """翻译单个术语"""
    term = term.strip()
    
    # 直接匹配
    if term in JARGON_DICT:
        return {
            "original": term,
            "translation": JARGON_DICT[term],
            "source": "dictionary",
            "related_terms": get_related_terms(term)
        }
    
    # 同义词匹配
    if term in SYNONYM_MAP:
        main_term = SYNONYM_MAP[term]
        if main_term in JARGON_DICT:
            return {
                "original": term,
                "translation": JARGON_DICT[main_term],
                "source": "synonym",
                "related_terms": get_related_terms(main_term)
            }
    
    # 模糊匹配（包含关系）
    for key, value in JARGON_DICT.items():
        if key in term or term in key:
            return {
                "original": term,
                "translation": value,
                "source": "fuzzy",
                "related_terms": get_related_terms(key)
            }
    
    # 未找到翻译
    return {
        "original": term,
        "translation": None,
        "source": "not_found",
        "related_terms": []
    }


# ============================================================
# 创建路由
# ============================================================
router = APIRouter(
    prefix="/api/jargon",
    tags=["黑话翻译"],
    responses={
        429: {"model": ErrorResponse, "description": "请求过于频繁"},
        500: {"model": ErrorResponse, "description": "服务器内部错误"}
    }
)


# ============================================================
# 依赖项
# ============================================================
async def get_client_ip(request: Request) -> str:
    """获取客户端IP地址"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_rate_limit(request: Request, client_ip: str = Depends(get_client_ip)):
    """检查速率限制"""
    if not rate_limiter.is_allowed(client_ip):
        remaining = rate_limiter.get_remaining(client_ip)
        reset_time = rate_limiter.get_reset_time(client_ip)
        
        logger.warning(f"速率限制触发 - IP: {client_ip}, 剩余: {remaining}, 重置时间: {reset_time}s")
        
        raise HTTPException(
            status_code=429,
            detail={
                "success": False,
                "error": "请求过于频繁",
                "detail": f"每小时限制{rate_limiter.max_requests}次请求，请{int(reset_time)}秒后重试",
                "remaining": remaining,
                "reset_after": int(reset_time)
            }
        )
    return client_ip


# ============================================================
# API 端点
# ============================================================
@router.get("/translate", response_model=TranslateResponse)
async def translate_get(
    text: str = Query(..., min_length=1, max_length=500, description="需要翻译的升学术语"),
    request: Request = None,
    client_ip: str = Depends(check_rate_limit)
):
    """
    GET方式翻译黑话
    
    将升学术语翻译为通俗易懂的语言，支持同义词和模糊匹配。
    """
    try:
        logger.info(f"翻译请求 - IP: {client_ip}, 文本: {text}")
        
        result = translate_term(text)
        
        if result["translation"] is None:
            logger.info(f"未找到翻译 - 文本: {text}")
            return TranslateResponse(
                success=True,
                original=text,
                translation=f"未找到「{text}」的翻译，请检查术语是否正确",
                source="not_found",
                related_terms=result["related_terms"]
            )
        
        logger.info(f"翻译成功 - 文本: {text}, 来源: {result['source']}")
        
        return TranslateResponse(
            success=True,
            original=result["original"],
            translation=result["translation"],
            source=result["source"],
            related_terms=result["related_terms"]
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"翻译失败 - 文本: {text}, 错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "翻译失败",
                "detail": f"服务器内部错误: {str(e)}"
            }
        )


@router.post("/translate", response_model=TranslateResponse)
async def translate_post(
    request_data: TranslateRequest,
    request: Request = None,
    client_ip: str = Depends(check_rate_limit)
):
    """
    POST方式翻译黑话
    
    将升学术语翻译为通俗易懂的语言，支持同义词和模糊匹配。
    """
    try:
        text = request_data.text
        logger.info(f"翻译请求(POST) - IP: {client_ip}, 文本: {text}")
        
        result = translate_term(text)
        
        if result["translation"] is None:
            logger.info(f"未找到翻译 - 文本: {text}")
            return TranslateResponse(
                success=True,
                original=text,
                translation=f"未找到「{text}」的翻译，请检查术语是否正确",
                source="not_found",
                related_terms=result["related_terms"]
            )
        
        logger.info(f"翻译成功 - 文本: {text}, 来源: {result['source']}")
        
        return TranslateResponse(
            success=True,
            original=result["original"],
            translation=result["translation"],
            source=result["source"],
            related_terms=result["related_terms"]
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"翻译失败 - 文本: {text}, 错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "翻译失败",
                "detail": f"服务器内部错误: {str(e)}"
            }
        )


@router.post("/translate/batch", response_model=BatchTranslateResponse)
async def translate_batch(
    request_data: BatchTranslateRequest,
    request: Request = None,
    client_ip: str = Depends(check_rate_limit)
):
    """
    批量翻译黑话
    
    同时翻译多个升学术语，返回每个术语的翻译结果。
    """
    try:
        texts = request_data.texts
        logger.info(f"批量翻译请求 - IP: {client_ip}, 数量: {len(texts)}")
        
        results = []
        found_count = 0
        not_found_count = 0
        
        for text in texts:
            result = translate_term(text)
            
            if result["translation"] is None:
                not_found_count += 1
                results.append({
                    "original": text,
                    "translation": f"未找到「{text}」的翻译",
                    "source": "not_found"
                })
            else:
                found_count += 1
                results.append({
                    "original": result["original"],
                    "translation": result["translation"],
                    "source": result["source"]
                })
        
        logger.info(f"批量翻译完成 - 总数: {len(texts)}, 成功: {found_count}, 失败: {not_found_count}")
        
        return BatchTranslateResponse(
            success=True,
            results=results,
            total=len(texts),
            found=found_count,
            not_found=not_found_count
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量翻译失败 - 错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "批量翻译失败",
                "detail": f"服务器内部错误: {str(e)}"
            }
        )


@router.get("/glossary", response_model=GlossaryResponse)
async def get_glossary(
    request: Request = None,
    client_ip: str = Depends(check_rate_limit)
):
    """
    获取完整术语表
    
    返回所有升学黑话术语及其通俗解释，按类别分类。
    """
    try:
        logger.info(f"获取术语表 - IP: {client_ip}")
        
        # 构建术语列表
        terms = [
            {"term": key, "definition": value}
            for key, value in JARGON_DICT.items()
        ]
        
        # 按首字母排序
        terms.sort(key=lambda x: x["term"])
        
        # 构建分类
        categories = {
            "招生方式": ["划片", "多校划片", "单校划片", "随机派位", "大摇号", "小摇号", "民办摇号", "直升", "调招", "统招"],
            "指标政策": ["指标到校", "市级指标", "区级指标"],
            "特殊类型": ["艺体特长生", "借读", "转学", "择校"],
            "学区房产": ["学区房", "学位预警", "落户年限", "六年一学位", "五年一学位"],
            "随迁子女": ["随迁子女", "积分入学"],
            "办学模式": ["两自一包", "名校集团", "领办", "对口", "九年一贯制", "十二年一贯制"],
            "学校俗称": ["五朵金花", "四七九", "二圈层", "三圈层"],
            "考试升学": ["零诊", "一诊", "二诊", "三诊", "调考", "中考", "高考", "小升初", "初升高", "幼升小"],
            "通用概念": ["K12"]
        }
        
        # 过滤分类中不存在的术语
        filtered_categories = {}
        for category, term_list in categories.items():
            valid_terms = [t for t in term_list if t in JARGON_DICT]
            if valid_terms:
                filtered_categories[category] = valid_terms
        
        logger.info(f"获取术语表成功 - 总数: {len(terms)}")
        
        return GlossaryResponse(
            success=True,
            total=len(terms),
            terms=terms,
            categories=filtered_categories
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取术语表失败 - 错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "获取术语表失败",
                "detail": f"服务器内部错误: {str(e)}"
            }
        )


@router.get("/search")
async def search_terms(
    q: str = Query(..., min_length=1, max_length=100, description="搜索关键词"),
    request: Request = None,
    client_ip: str = Depends(check_rate_limit)
):
    """
    搜索术语
    
    根据关键词搜索匹配的升学黑话术语。
    """
    try:
        logger.info(f"搜索术语 - IP: {client_ip}, 关键词: {q}")
        
        results = []
        
        # 精确匹配
        if q in JARGON_DICT:
            results.append({
                "term": q,
                "definition": JARGON_DICT[q],
                "match_type": "exact"
            })
        
        # 前缀匹配
        for key, value in JARGON_DICT.items():
            if key != q and key.startswith(q):
                results.append({
                    "term": key,
                    "definition": value,
                    "match_type": "prefix"
                })
        
        # 包含匹配
        for key, value in JARGON_DICT.items():
            if key != q and not key.startswith(q) and q in key:
                results.append({
                    "term": key,
                    "definition": value,
                    "match_type": "contains"
                })
        
        # 同义词匹配
        if q in SYNONYM_MAP:
            main_term = SYNONYM_MAP[q]
            if main_term in JARGON_DICT:
                results.append({
                    "term": q,
                    "definition": JARGON_DICT[main_term],
                    "match_type": "synonym"
                })
        
        # 去重
        seen = set()
        unique_results = []
        for result in results:
            if result["term"] not in seen:
                seen.add(result["term"])
                unique_results.append(result)
        
        # 限制结果数量
        unique_results = unique_results[:20]
        
        logger.info(f"搜索完成 - 关键词: {q}, 结果数: {len(unique_results)}")
        
        return {
            "success": True,
            "query": q,
            "total": len(unique_results),
            "results": unique_results
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"搜索失败 - 关键词: {q}, 错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "搜索失败",
                "detail": f"服务器内部错误: {str(e)}"
            }
        )


@router.get("/rate-limit")
async def get_rate_limit_status(
    request: Request,
    client_ip: str = Depends(get_client_ip)
):
    """
    获取当前速率限制状态
    
    返回当前客户端的速率限制使用情况。
    """
    try:
        remaining = rate_limiter.get_remaining(client_ip)
        reset_time = rate_limiter.get_reset_time(client_ip)
        
        return {
            "success": True,
            "max_requests": rate_limiter.max_requests,
            "remaining": remaining,
            "reset_after": int(reset_time),
            "window_seconds": rate_limiter.window_seconds
        }
    
    except Exception as e:
        logger.error(f"获取速率限制状态失败 - 错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "获取速率限制状态失败",
                "detail": f"服务器内部错误: {str(e)}"
            }
        )


# ============================================================
# 健康检查端点
# ============================================================
@router.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "service": "jargon-translator",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "dictionary_size": len(JARGON_DICT),
        "synonym_count": len(SYNONYM_MAP)
    }
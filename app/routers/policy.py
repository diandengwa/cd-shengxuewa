#!/usr/bin/env python3
"""
政策查询API路由 — 成都K12升学参谋
支持按学段/区域/年份筛选，返回结构化政策数据，速率限制60次/小时
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent

logger = logging.getLogger("k12.policy")

router = APIRouter(
    prefix="/api/policy",
    tags=["政策查询"],
    responses={404: {"description": "未找到相关政策"}},
)

# ============================================================
# 数据模型
# ============================================================

class PolicyItem(BaseModel):
    """政策条目模型"""
    id: int = Field(..., description="政策ID")
    title: str = Field(..., description="政策标题")
    summary: str = Field(..., description="政策摘要")
    content: str = Field(..., description="政策全文")
    grade: str = Field(..., description="学段: 小学/初中/高中/全学段")
    region: str = Field(..., description="区域: 锦江区/青羊区/金牛区/武侯区/成华区/高新区/天府新区/全市")
    year: int = Field(..., description="发布年份")
    publish_date: str = Field(..., description="发布日期 YYYY-MM-DD")
    source: str = Field(..., description="来源: 教育局/学校/官方媒体")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    url: Optional[str] = Field(None, description="原文链接")

class PolicyQueryResponse(BaseModel):
    """政策查询响应模型"""
    code: int = Field(200, description="状态码")
    message: str = Field("success", description="状态消息")
    total: int = Field(0, description="总数")
    policies: List[PolicyItem] = Field(default_factory=list, description="政策列表")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页数量")

# ============================================================
# 速率限制（内存实现，60次/小时）
# ============================================================

class RateLimiter:
    """简单的内存速率限制器"""
    
    def __init__(self, max_requests: int = 60, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = {}
    
    def check(self, client_ip: str) -> bool:
        """检查是否允许请求"""
        now = time.time()
        window_start = now - self.window_seconds
        
        # 清理过期记录
        if client_ip in self.requests:
            self.requests[client_ip] = [
                t for t in self.requests[client_ip] if t > window_start
            ]
        else:
            self.requests[client_ip] = []
        
        # 检查是否超过限制
        if len(self.requests[client_ip]) >= self.max_requests:
            return False
        
        # 记录本次请求
        self.requests[client_ip].append(now)
        return True

# 全局速率限制器实例
rate_limiter = RateLimiter(max_requests=60, window_seconds=3600)

# ============================================================
# 速率限制装饰器
# ============================================================

def rate_limit(max_requests: int = 60, window_seconds: int = 3600):
    """
    速率限制装饰器
    限制每个IP在指定时间窗口内的请求次数
    
    Args:
        max_requests: 最大请求次数
        window_seconds: 时间窗口（秒）
    """
    limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
    
    def decorator(func):
        async def wrapper(request: Request, *args, **kwargs):
            # 获取客户端IP
            client_ip = request.client.host if request.client else "unknown"
            
            # 检查速率限制
            if not limiter.check(client_ip):
                logger.warning(f"IP {client_ip} 请求频率过高，已限制")
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": 429,
                        "message": "请求过于频繁，请稍后再试",
                        "max_requests": max_requests,
                        "window_seconds": window_seconds
                    }
                )
            
            return await func(request, *args, **kwargs)
        
        return wrapper
    
    return decorator

# ============================================================
# 模拟数据（实际项目应接入数据库）
# ============================================================

def load_mock_policies() -> List[Dict[str, Any]]:
    """
    加载模拟政策数据
    实际项目中应替换为数据库查询
    """
    return [
        {
            "id": 1,
            "title": "成都市2024年义务教育阶段学校招生入学工作通知",
            "summary": "明确2024年成都市小学、初中招生入学政策，包括划片范围、报名时间、录取方式等",
            "content": "根据《中华人民共和国义务教育法》和教育部有关文件精神，结合我市实际，现就2024年全市义务教育阶段学校招生入学工作通知如下：一、坚持免试就近入学原则...",
            "grade": "全学段",
            "region": "全市",
            "year": 2024,
            "publish_date": "2024-03-15",
            "source": "成都市教育局",
            "tags": ["招生", "义务教育", "入学政策"],
            "url": "https://www.cdedu.gov.cn/2024/0315/12345.html"
        },
        {
            "id": 2,
            "title": "锦江区2024年小学入学划片范围公告",
            "summary": "公布锦江区各小学招生划片范围，包括户籍要求、登记时间等详细信息",
            "content": "按照成都市教育局统一部署，现将锦江区2024年小学一年级入学划片范围公告如下：...",
            "grade": "小学",
            "region": "锦江区",
            "year": 2024,
            "publish_date": "2024-04-01",
            "source": "锦江区教育局",
            "tags": ["划片", "小学入学", "锦江区"],
            "url": "https://www.cdedu.gov.cn/2024/0401/12346.html"
        },
        {
            "id": 3,
            "title": "成都市2024年中考政策解读",
            "summary": "详细解读2024年成都市中考报名、考试、志愿填报及录取政策变化",
            "content": "2024年成都市中考政策主要有以下变化：一、考试科目调整...二、志愿填报方式优化...",
            "grade": "初中",
            "region": "全市",
            "year": 2024,
            "publish_date": "2024-03-20",
            "source": "成都市教育考试院",
            "tags": ["中考", "考试政策", "志愿填报"],
            "url": "https://www.cdedu.gov.cn/2024/0320/12347.html"
        },
        {
            "id": 4,
            "title": "高新区2024年随迁子女入学政策",
            "summary": "明确高新区随迁子女入学条件、申请流程及所需材料",
            "content": "为做好高新区随迁子女接受义务教育工作，根据相关文件精神，现将2024年随迁子女入学政策公布如下：...",
            "grade": "全学段",
            "region": "高新区",
            "year": 2024,
            "publish_date": "2024-02-28",
            "source": "高新区教育文化体育局",
            "tags": ["随迁子女", "入学政策", "高新区"],
            "url": "https://www.cdedu.gov.cn/2024/0228/12348.html"
        },
        {
            "id": 5,
            "title": "成都市2023年高中阶段学校招生计划",
            "summary": "公布2023年全市普通高中、职业高中招生计划及录取分数线",
            "content": "根据成都市教育局统一安排，现将2023年全市高中阶段学校招生计划公布如下：...",
            "grade": "高中",
            "region": "全市",
            "year": 2023,
            "publish_date": "2023-06-15",
            "source": "成都市教育局",
            "tags": ["高中招生", "招生计划", "录取分数线"],
            "url": "https://www.cdedu.gov.cn/2023/0615/12349.html"
        },
        {
            "id": 6,
            "title": "武侯区2024年幼儿园升小学政策",
            "summary": "武侯区2024年幼儿园升小学的报名条件、时间安排及录取规则",
            "content": "武侯区2024年小学入学工作即将开始，现将相关政策和安排通知如下：...",
            "grade": "小学",
            "region": "武侯区",
            "year": 2024,
            "publish_date": "2024-03-10",
            "source": "武侯区教育局",
            "tags": ["幼升小", "武侯区", "入学政策"],
            "url": "https://www.cdedu.gov.cn/2024/0310/12350.html"
        },
        {
            "id": 7,
            "title": "成都市2024年小升初多校划片政策",
            "summary": "详细说明成都市2024年小升初多校划片的具体实施方案",
            "content": "为促进教育公平，2024年成都市将继续实施小升初多校划片政策，具体方案如下：...",
            "grade": "初中",
            "region": "全市",
            "year": 2024,
            "publish_date": "2024-04-05",
            "source": "成都市教育局",
            "tags": ["小升初", "多校划片", "教育公平"],
            "url": "https://www.cdedu.gov.cn/2024/0405/12351.html"
        },
        {
            "id": 8,
            "title": "金牛区2024年义务教育阶段学校招生工作细则",
            "summary": "金牛区2024年义务教育阶段学校招生的具体工作安排",
            "content": "根据成都市教育局相关要求，结合金牛区实际，现将2024年义务教育阶段学校招生工作细则公布如下：...",
            "grade": "全学段",
            "region": "金牛区",
            "year": 2024,
            "publish_date": "2024-03-25",
            "source": "金牛区教育局",
            "tags": ["招生细则", "金牛区", "义务教育"],
            "url": "https://www.cdedu.gov.cn/2024/0325/12352.html"
        },
        {
            "id": 9,
            "title": "成都市2023年普通高中录取分数线",
            "summary": "2023年成都市各普通高中录取分数线及招生计划完成情况",
            "content": "2023年成都市普通高中录取工作已结束，现将各校录取分数线公布如下：...",
            "grade": "高中",
            "region": "全市",
            "year": 2023,
            "publish_date": "2023-07-20",
            "source": "成都市教育考试院",
            "tags": ["录取分数线", "高中", "招生"],
            "url": "https://www.cdedu.gov.cn/2023/0720/12353.html"
        },
        {
            "id": 10,
            "title": "天府新区2024年新办学校招生政策",
            "summary": "天府新区2024年新开办学校的招生范围、条件及报名方式",
            "content": "为满足天府新区适龄儿童入学需求，2024年将新开办5所中小学，现将招生政策公布如下：...",
            "grade": "全学段",
            "region": "天府新区",
            "year": 2024,
            "publish_date": "2024-01-15",
            "source": "天府新区社区治理和社事局",
            "tags": ["新办学校", "天府新区", "招生政策"],
            "url": "https://www.cdedu.gov.cn/2024/0115/12354.html"
        }
    ]

# ============================================================
# 数据过滤函数
# ============================================================

def filter_policies(
    policies: List[Dict[str, Any]],
    grade: Optional[str] = None,
    region: Optional[str] = None,
    year: Optional[int] = None,
    keyword: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    根据筛选条件过滤政策数据
    
    Args:
        policies: 政策数据列表
        grade: 学段筛选
        region: 区域筛选
        year: 年份筛选
        keyword: 关键词搜索
    
    Returns:
        过滤后的政策列表
    """
    filtered = policies.copy()
    
    # 学段筛选（支持全学段匹配）
    if grade:
        filtered = [
            p for p in filtered 
            if p["grade"] == grade or p["grade"] == "全学段"
        ]
    
    # 区域筛选（支持全市匹配）
    if region:
        filtered = [
            p for p in filtered 
            if p["region"] == region or p["region"] == "全市"
        ]
    
    # 年份筛选
    if year:
        filtered = [p for p in filtered if p["year"] == year]
    
    # 关键词搜索（在标题、摘要、内容中搜索）
    if keyword:
        keyword_lower = keyword.lower()
        filtered = [
            p for p in filtered
            if keyword_lower in p["title"].lower()
            or keyword_lower in p["summary"].lower()
            or keyword_lower in p["content"].lower()
            or any(keyword_lower in tag.lower() for tag in p["tags"])
        ]
    
    return filtered

# ============================================================
# API 路由
# ============================================================

@router.get("/query", response_model=PolicyQueryResponse)
@rate_limit(max_requests=60, window_seconds=3600)
async def query_policies(
    request: Request,
    grade: Optional[str] = Query(None, description="学段: 小学/初中/高中/全学段"),
    region: Optional[str] = Query(None, description="区域: 锦江区/青羊区/金牛区/武侯区/成华区/高新区/天府新区/全市"),
    year: Optional[int] = Query(None, description="发布年份，如2024"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量")
):
    """
    查询政策信息
    
    支持按学段、区域、年份和关键词进行筛选，返回分页的政策数据。
    每个IP每小时最多请求60次。
    
    Args:
        request: 请求对象
        grade: 学段筛选
        region: 区域筛选
        year: 年份筛选
        keyword: 关键词搜索
        page: 当前页码
        page_size: 每页数量
    
    Returns:
        政策查询响应
    """
    try:
        # 记录请求参数
        logger.info(
            f"政策查询请求 - IP: {request.client.host if request.client else 'unknown'}, "
            f"参数: grade={grade}, region={region}, year={year}, "
            f"keyword={keyword}, page={page}, page_size={page_size}"
        )
        
        # 加载政策数据
        all_policies = load_mock_policies()
        
        # 应用筛选条件
        filtered_policies = filter_policies(
            all_policies,
            grade=grade,
            region=region,
            year=year,
            keyword=keyword
        )
        
        # 计算总数
        total = len(filtered_policies)
        
        # 分页处理
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_policies = filtered_policies[start_idx:end_idx]
        
        # 转换为PolicyItem模型
        policy_items = [PolicyItem(**p) for p in page_policies]
        
        # 记录查询结果
        logger.info(
            f"政策查询结果 - 总数: {total}, "
            f"返回: {len(policy_items)}条, "
            f"页码: {page}/{max(1, (total + page_size - 1) // page_size)}"
        )
        
        return PolicyQueryResponse(
            code=200,
            message="success",
            total=total,
            policies=policy_items,
            page=page,
            page_size=page_size
        )
    
    except Exception as e:
        logger.error(f"政策查询失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500,
                "message": f"政策查询失败: {str(e)}"
            }
        )

@router.get("/grades", response_model=Dict[str, Any])
async def get_available_grades():
    """
    获取可用的学段列表
    
    Returns:
        学段列表
    """
    try:
        grades = ["小学", "初中", "高中", "全学段"]
        return {
            "code": 200,
            "message": "success",
            "data": grades
        }
    except Exception as e:
        logger.error(f"获取学段列表失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500,
                "message": f"获取学段列表失败: {str(e)}"
            }
        )

@router.get("/regions", response_model=Dict[str, Any])
async def get_available_regions():
    """
    获取可用的区域列表
    
    Returns:
        区域列表
    """
    try:
        regions = [
            "锦江区", "青羊区", "金牛区", "武侯区", 
            "成华区", "高新区", "天府新区", "全市"
        ]
        return {
            "code": 200,
            "message": "success",
            "data": regions
        }
    except Exception as e:
        logger.error(f"获取区域列表失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500,
                "message": f"获取区域列表失败: {str(e)}"
            }
        )

@router.get("/years", response_model=Dict[str, Any])
async def get_available_years():
    """
    获取可用的年份列表
    
    Returns:
        年份列表
    """
    try:
        # 从数据中提取所有年份
        all_policies = load_mock_policies()
        years = sorted(set(p["year"] for p in all_policies), reverse=True)
        
        return {
            "code": 200,
            "message": "success",
            "data": years
        }
    except Exception as e:
        logger.error(f"获取年份列表失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500,
                "message": f"获取年份列表失败: {str(e)}"
            }
        )

@router.get("/detail/{policy_id}", response_model=Dict[str, Any])
async def get_policy_detail(policy_id: int):
    """
    获取政策详情
    
    Args:
        policy_id: 政策ID
    
    Returns:
        政策详情
    """
    try:
        # 加载政策数据
        all_policies = load_mock_policies()
        
        # 查找指定ID的政策
        policy = next(
            (p for p in all_policies if p["id"] == policy_id),
            None
        )
        
        if not policy:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": 404,
                    "message": f"未找到ID为 {policy_id} 的政策"
                }
            )
        
        return {
            "code": 200,
            "message": "success",
            "data": PolicyItem(**policy)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取政策详情失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500,
                "message": f"获取政策详情失败: {str(e)}"
            }
        )

# ============================================================
# 健康检查端点
# ============================================================

@router.get("/health", response_model=Dict[str, Any])
async def health_check():
    """
    健康检查端点
    
    Returns:
        服务状态
    """
    return {
        "code": 200,
        "message": "success",
        "data": {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service": "policy-query-api",
            "version": "2.0.0"
        }
    }
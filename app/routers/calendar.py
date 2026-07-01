#!/usr/bin/env python3
"""
升学日历API路由 — 返回关键升学节点事件
速率限制: 60次/小时
"""

import json
import logging
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

# 尝试导入速率限制中间件，若不存在则降级
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    HAS_SLOWAPI = True
except ImportError:
    HAS_SLOWAPI = False
    logging.warning("slowapi 未安装，速率限制功能将不可用")

logger = logging.getLogger(__name__)

router = APIRouter(
    
    tags=["升学日历"],
    responses={404: {"description": "未找到"}},
)

# ============================================================
# 数据模型
# ============================================================

class CalendarEvent(BaseModel):
    """升学日历事件模型"""
    id: str = Field(..., description="事件唯一标识")
    title: str = Field(..., description="事件标题")
    description: Optional[str] = Field(None, description="事件描述")
    start_date: date = Field(..., description="开始日期")
    end_date: Optional[date] = Field(None, description="结束日期")
    event_type: str = Field(..., description="事件类型: exam/registration/notice/other")
    grade: Optional[str] = Field(None, description="适用年级")
    region: str = Field(default="成都", description="适用区域")
    url: Optional[str] = Field(None, description="相关链接")
    is_important: bool = Field(default=False, description="是否重要事件")

class CalendarResponse(BaseModel):
    """日历响应模型"""
    events: List[CalendarEvent] = Field(..., description="事件列表")
    total: int = Field(..., description="事件总数")
    year: int = Field(..., description="年份")
    month: Optional[int] = Field(None, description="月份")

# ============================================================
# 模拟数据源 — 实际项目应替换为数据库查询
# ============================================================

def _load_events_from_json() -> List[dict]:
    """从JSON文件加载升学事件数据"""
    events_file = Path(__file__).parent.parent / "data" / "calendar_events.json"
    if events_file.exists():
        try:
            with open(events_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"加载升学事件数据失败: {e}")
            return []
    return []

def _get_default_events() -> List[dict]:
    """获取默认的升学事件数据（当JSON文件不存在时使用）"""
    current_year = datetime.now().year
    return [
        {
            "id": "exam-001",
            "title": "成都市中考报名",
            "description": "成都市高中阶段教育学校统一招生考试报名",
            "start_date": f"{current_year}-03-01",
            "end_date": f"{current_year}-03-15",
            "event_type": "registration",
            "grade": "初三",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": True
        },
        {
            "id": "exam-002",
            "title": "成都市中考",
            "description": "成都市高中阶段教育学校统一招生考试",
            "start_date": f"{current_year}-06-13",
            "end_date": f"{current_year}-06-14",
            "event_type": "exam",
            "grade": "初三",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": True
        },
        {
            "id": "exam-003",
            "title": "中考成绩公布",
            "description": "成都市中考成绩查询及分数线公布",
            "start_date": f"{current_year}-06-28",
            "end_date": None,
            "event_type": "notice",
            "grade": "初三",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": True
        },
        {
            "id": "exam-004",
            "title": "中考志愿填报",
            "description": "成都市中考志愿填报系统开放",
            "start_date": f"{current_year}-06-29",
            "end_date": f"{current_year}-07-05",
            "event_type": "registration",
            "grade": "初三",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": True
        },
        {
            "id": "exam-005",
            "title": "小升初信息采集",
            "description": "成都市小学毕业生初中入学信息采集",
            "start_date": f"{current_year}-04-20",
            "end_date": f"{current_year}-04-30",
            "event_type": "registration",
            "grade": "六年级",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": True
        },
        {
            "id": "exam-006",
            "title": "小升初划片公布",
            "description": "成都市小升初划片范围公布",
            "start_date": f"{current_year}-07-10",
            "end_date": None,
            "event_type": "notice",
            "grade": "六年级",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": True
        },
        {
            "id": "exam-007",
            "title": "小升初随机派位",
            "description": "成都市小升初随机派位及结果公布",
            "start_date": f"{current_year}-07-15",
            "end_date": f"{current_year}-07-17",
            "event_type": "exam",
            "grade": "六年级",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": True
        },
        {
            "id": "exam-008",
            "title": "高考报名",
            "description": "四川省普通高考报名",
            "start_date": f"{current_year}-10-10",
            "end_date": f"{current_year}-10-20",
            "event_type": "registration",
            "grade": "高三",
            "region": "成都",
            "url": "https://www.sceea.cn",
            "is_important": True
        },
        {
            "id": "exam-009",
            "title": "高考体检",
            "description": "成都市高考体检安排",
            "start_date": f"{current_year}-03-01",
            "end_date": f"{current_year}-04-30",
            "event_type": "other",
            "grade": "高三",
            "region": "成都",
            "url": "https://www.sceea.cn",
            "is_important": False
        },
        {
            "id": "exam-010",
            "title": "高考",
            "description": "全国普通高等学校招生统一考试",
            "start_date": f"{current_year}-06-07",
            "end_date": f"{current_year}-06-08",
            "event_type": "exam",
            "grade": "高三",
            "region": "成都",
            "url": "https://www.sceea.cn",
            "is_important": True
        },
        {
            "id": "exam-011",
            "title": "高考成绩公布",
            "description": "四川省高考成绩查询及分数线公布",
            "start_date": f"{current_year}-06-23",
            "end_date": None,
            "event_type": "notice",
            "grade": "高三",
            "region": "成都",
            "url": "https://www.sceea.cn",
            "is_important": True
        },
        {
            "id": "exam-012",
            "title": "高考志愿填报",
            "description": "四川省高考志愿填报系统开放",
            "start_date": f"{current_year}-06-24",
            "end_date": f"{current_year}-07-05",
            "event_type": "registration",
            "grade": "高三",
            "region": "成都",
            "url": "https://www.sceea.cn",
            "is_important": True
        },
        {
            "id": "exam-013",
            "title": "幼升小信息登记",
            "description": "成都市小学一年级入学信息登记",
            "start_date": f"{current_year}-05-10",
            "end_date": f"{current_year}-05-20",
            "event_type": "registration",
            "grade": "学前",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": True
        },
        {
            "id": "exam-014",
            "title": "幼升小划片公布",
            "description": "成都市小学一年级划片范围公布",
            "start_date": f"{current_year}-06-15",
            "end_date": None,
            "event_type": "notice",
            "grade": "学前",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": True
        },
        {
            "id": "exam-015",
            "title": "期末考试",
            "description": "成都市中小学期末考试安排",
            "start_date": f"{current_year}-01-10",
            "end_date": f"{current_year}-01-15",
            "event_type": "exam",
            "grade": "全部",
            "region": "成都",
            "url": None,
            "is_important": False
        },
        {
            "id": "exam-016",
            "title": "寒假开始",
            "description": "成都市中小学寒假开始",
            "start_date": f"{current_year}-01-20",
            "end_date": f"{current_year}-02-15",
            "event_type": "other",
            "grade": "全部",
            "region": "成都",
            "url": None,
            "is_important": False
        },
        {
            "id": "exam-017",
            "title": "暑假开始",
            "description": "成都市中小学暑假开始",
            "start_date": f"{current_year}-07-01",
            "end_date": f"{current_year}-08-31",
            "event_type": "other",
            "grade": "全部",
            "region": "成都",
            "url": None,
            "is_important": False
        },
        {
            "id": "exam-018",
            "title": "春季开学",
            "description": "成都市中小学春季学期开学",
            "start_date": f"{current_year}-02-16",
            "end_date": None,
            "event_type": "other",
            "grade": "全部",
            "region": "成都",
            "url": None,
            "is_important": False
        },
        {
            "id": "exam-019",
            "title": "秋季开学",
            "description": "成都市中小学秋季学期开学",
            "start_date": f"{current_year}-09-01",
            "end_date": None,
            "event_type": "other",
            "grade": "全部",
            "region": "成都",
            "url": None,
            "is_important": False
        },
        {
            "id": "exam-020",
            "title": "艺术特长生测试",
            "description": "成都市高中艺术特长生专业测试",
            "start_date": f"{current_year}-05-20",
            "end_date": f"{current_year}-05-25",
            "event_type": "exam",
            "grade": "初三",
            "region": "成都",
            "url": "https://www.cdzk.org",
            "is_important": False
        }
    ]

def _get_events() -> List[dict]:
    """获取事件数据，优先从JSON文件加载，否则使用默认数据"""
    events = _load_events_from_json()
    if not events:
        events = _get_default_events()
    return events

# ============================================================
# 速率限制依赖
# ============================================================

def get_limiter() -> Optional[Limiter]:
    """获取速率限制器实例"""
    if HAS_SLOWAPI:
        return Limiter(key_func=get_remote_address)
    return None

# ============================================================
# API路由
# ============================================================

@router.get("/events", response_model=CalendarResponse, summary="获取升学日历事件")
async def get_calendar_events(
    request: Request,
    year: Optional[int] = Query(None, description="年份，默认当前年份"),
    month: Optional[int] = Query(None, ge=1, le=12, description="月份（1-12），可选"),
    grade: Optional[str] = Query(None, description="年级筛选，如：初三、高三、六年级"),
    event_type: Optional[str] = Query(None, description="事件类型筛选：exam/registration/notice/other"),
    important_only: bool = Query(False, description="仅返回重要事件"),
    region: Optional[str] = Query(None, description="区域筛选，默认成都"),
    keyword: Optional[str] = Query(None, description="关键词搜索（标题/描述）"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，最大100")
):
    """
    获取升学日历事件列表
    
    支持按年份、月份、年级、事件类型、区域、关键词筛选，
    支持分页和仅显示重要事件。
    """
    try:
        # 获取当前年份
        current_year = datetime.now().year
        target_year = year if year else current_year
        
        # 获取所有事件
        all_events = _get_events()
        
        # 筛选年份
        filtered_events = []
        for event in all_events:
            try:
                event_start = datetime.strptime(event["start_date"], "%Y-%m-%d").date()
                if event_start.year == target_year:
                    filtered_events.append(event)
            except (ValueError, KeyError):
                continue
        
        # 月份筛选
        if month:
            month_filtered = []
            for event in filtered_events:
                try:
                    event_start = datetime.strptime(event["start_date"], "%Y-%m-%d").date()
                    if event_start.month == month:
                        month_filtered.append(event)
                except (ValueError, KeyError):
                    continue
            filtered_events = month_filtered
        
        # 年级筛选
        if grade:
            filtered_events = [
                e for e in filtered_events 
                if e.get("grade") and grade in e["grade"]
            ]
        
        # 事件类型筛选
        if event_type:
            filtered_events = [
                e for e in filtered_events 
                if e.get("event_type") == event_type
            ]
        
        # 重要事件筛选
        if important_only:
            filtered_events = [
                e for e in filtered_events 
                if e.get("is_important", False)
            ]
        
        # 区域筛选
        if region:
            filtered_events = [
                e for e in filtered_events 
                if e.get("region") and region in e["region"]
            ]
        
        # 关键词搜索
        if keyword:
            keyword_lower = keyword.lower()
            filtered_events = [
                e for e in filtered_events 
                if keyword_lower in e.get("title", "").lower() 
                or keyword_lower in e.get("description", "").lower()
            ]
        
        # 按开始日期排序
        filtered_events.sort(key=lambda x: x.get("start_date", ""))
        
        # 计算总数
        total = len(filtered_events)
        
        # 分页
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paged_events = filtered_events[start_idx:end_idx]
        
        # 转换为CalendarEvent模型
        events = []
        for event in paged_events:
            try:
                calendar_event = CalendarEvent(
                    id=event["id"],
                    title=event["title"],
                    description=event.get("description"),
                    start_date=datetime.strptime(event["start_date"], "%Y-%m-%d").date(),
                    end_date=datetime.strptime(event["end_date"], "%Y-%m-%d").date() if event.get("end_date") else None,
                    event_type=event["event_type"],
                    grade=event.get("grade"),
                    region=event.get("region", "成都"),
                    url=event.get("url"),
                    is_important=event.get("is_important", False)
                )
                events.append(calendar_event)
            except (KeyError, ValueError) as e:
                logger.warning(f"事件数据解析失败: {e}, 事件: {event.get('id', 'unknown')}")
                continue
        
        return CalendarResponse(
            events=events,
            total=total,
            year=target_year,
            month=month
        )
        
    except Exception as e:
        logger.error(f"获取升学日历事件失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取升学日历事件失败: {str(e)}"
        )


@router.get("/events/today", response_model=List[CalendarEvent], summary="获取今日升学事件")
async def get_today_events(
    request: Request,
    grade: Optional[str] = Query(None, description="年级筛选"),
    region: Optional[str] = Query(None, description="区域筛选")
):
    """
    获取今日发生的升学事件
    
    返回今天开始或正在进行的升学关键节点事件。
    """
    try:
        today = date.today()
        all_events = _get_events()
        
        today_events = []
        for event in all_events:
            try:
                event_start = datetime.strptime(event["start_date"], "%Y-%m-%d").date()
                event_end = datetime.strptime(event["end_date"], "%Y-%m-%d").date() if event.get("end_date") else event_start
                
                # 判断事件是否在今天发生或正在进行
                if event_start <= today <= event_end:
                    # 年级筛选
                    if grade and event.get("grade") and grade not in event["grade"]:
                        continue
                    # 区域筛选
                    if region and event.get("region") and region not in event["region"]:
                        continue
                    
                    today_events.append(event)
            except (ValueError, KeyError):
                continue
        
        # 转换为CalendarEvent模型
        events = []
        for event in today_events:
            try:
                calendar_event = CalendarEvent(
                    id=event["id"],
                    title=event["title"],
                    description=event.get("description"),
                    start_date=datetime.strptime(event["start_date"], "%Y-%m-%d").date(),
                    end_date=datetime.strptime(event["end_date"], "%Y-%m-%d").date() if event.get("end_date") else None,
                    event_type=event["event_type"],
                    grade=event.get("grade"),
                    region=event.get("region", "成都"),
                    url=event.get("url"),
                    is_important=event.get("is_important", False)
                )
                events.append(calendar_event)
            except (KeyError, ValueError) as e:
                logger.warning(f"事件数据解析失败: {e}")
                continue
        
        return events
        
    except Exception as e:
        logger.error(f"获取今日升学事件失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取今日升学事件失败: {str(e)}"
        )


@router.get("/events/upcoming", response_model=List[CalendarEvent], summary="获取即将到来的升学事件")
async def get_upcoming_events(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="未来天数，默认30天"),
    grade: Optional[str] = Query(None, description="年级筛选"),
    event_type: Optional[str] = Query(None, description="事件类型筛选"),
    limit: int = Query(10, ge=1, le=50, description="返回数量限制")
):
    """
    获取即将到来的升学事件
    
    返回未来指定天数内的升学关键节点事件，按日期排序。
    """
    try:
        today = date.today()
        future_date = today + timedelta(days=days)
        all_events = _get_events()
        
        upcoming_events = []
        for event in all_events:
            try:
                event_start = datetime.strptime(event["start_date"], "%Y-%m-%d").date()
                
                # 判断事件是否在未来指定天数内
                if today <= event_start <= future_date:
                    # 年级筛选
                    if grade and event.get("grade") and grade not in event["grade"]:
                        continue
                    # 事件类型筛选
                    if event_type and event.get("event_type") != event_type:
                        continue
                    
                    upcoming_events.append(event)
            except (ValueError, KeyError):
                continue
        
        # 按开始日期排序
        upcoming_events.sort(key=lambda x: x.get("start_date", ""))
        
        # 限制返回数量
        upcoming_events = upcoming_events[:limit]
        
        # 转换为CalendarEvent模型
        events = []
        for event in upcoming_events:
            try:
                calendar_event = CalendarEvent(
                    id=event["id"],
                    title=event["title"],
                    description=event.get("description"),
                    start_date=datetime.strptime(event["start_date"], "%Y-%m-%d").date(),
                    end_date=datetime.strptime(event["end_date"], "%Y-%m-%d").date() if event.get("end_date") else None,
                    event_type=event["event_type"],
                    grade=event.get("grade"),
                    region=event.get("region", "成都"),
                    url=event.get("url"),
                    is_important=event.get("is_important", False)
                )
                events.append(calendar_event)
            except (KeyError, ValueError) as e:
                logger.warning(f"事件数据解析失败: {e}")
                continue
        
        return events
        
    except Exception as e:
        logger.error(f"获取即将到来的升学事件失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取即将到来的升学事件失败: {str(e)}"
        )


@router.get("/events/{event_id}", response_model=CalendarEvent, summary="获取单个升学事件详情")
async def get_event_detail(
    request: Request,
    event_id: str
):
    """
    根据事件ID获取单个升学事件的详细信息
    """
    try:
        all_events = _get_events()
        
        # 查找事件
        for event in all_events:
            if event.get("id") == event_id:
                try:
                    return CalendarEvent(
                        id=event["id"],
                        title=event["title"],
                        description=event.get("description"),
                        start_date=datetime.strptime(event["start_date"], "%Y-%m-%d").date(),
                        end_date=datetime.strptime(event["end_date"], "%Y-%m-%d").date() if event.get("end_date") else None,
                        event_type=event["event_type"],
                        grade=event.get("grade"),
                        region=event.get("region", "成都"),
                        url=event.get("url"),
                        is_important=event.get("is_important", False)
                    )
                except (KeyError, ValueError) as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"事件数据解析失败: {str(e)}"
                    )
        
        raise HTTPException(
            status_code=404,
            detail=f"未找到事件: {event_id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取事件详情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取事件详情失败: {str(e)}"
        )


@router.get("/stats", summary="获取升学日历统计信息")
async def get_calendar_stats(
    request: Request,
    year: Optional[int] = Query(None, description="年份，默认当前年份")
):
    """
    获取升学日历的统计信息
    
    包括各类型事件数量、各年级事件数量、月度分布等。
    """
    try:
        current_year = datetime.now().year
        target_year = year if year else current_year
        
        all_events = _get_events()
        
        # 筛选年份
        year_events = []
        for event in all_events:
            try:
                event_start = datetime.strptime(event["start_date"], "%Y-%m-%d").date()
                if event_start.year == target_year:
                    year_events.append(event)
            except (ValueError, KeyError):
                continue
        
        # 统计各类型事件数量
        type_stats = {}
        for event in year_events:
            event_type = event.get("event_type", "other")
            type_stats[event_type] = type_stats.get(event_type, 0) + 1
        
        # 统计各年级事件数量
        grade_stats = {}
        for event in year_events:
            grade = event.get("grade", "未知")
            grade_stats[grade] = grade_stats.get(grade, 0) + 1
        
        # 统计月度分布
        month_stats = {}
        for event in year_events:
            try:
                event_start = datetime.strptime(event["start_date"], "%Y-%m-%d").date()
                month = event_start.month
                month_stats[month] = month_stats.get(month, 0) + 1
            except (ValueError, KeyError):
                continue
        
        # 统计重要事件数量
        important_count = sum(1 for e in year_events if e.get("is_important", False))
        
        return {
            "year": target_year,
            "total_events": len(year_events),
            "important_events": important_count,
            "type_distribution": type_stats,
            "grade_distribution": grade_stats,
            "monthly_distribution": {str(k): v for k, v in sorted(month_stats.items())},
            "event_types": {
                "exam": "考试",
                "registration": "报名",
                "notice": "通知",
                "other": "其他"
            }
        }
        
    except Exception as e:
        logger.error(f"获取升学日历统计信息失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取升学日历统计信息失败: {str(e)}"
        )
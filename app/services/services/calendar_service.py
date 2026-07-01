#!/usr/bin/env python3
"""
升学日历服务层：从knowledge-base中提取关键升学节点，生成结构化日历数据
支持政策查询与诊断一站式服务的事件查询逻辑
"""

import json
import logging
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)


class CalendarEvent:
    """升学日历事件模型"""
    
    def __init__(
        self,
        event_id: str,
        title: str,
        start_date: date,
        end_date: Optional[date] = None,
        event_type: str = "general",
        description: str = "",
        grade: Optional[str] = None,
        region: str = "成都",
        source: str = "knowledge_base",
        url: Optional[str] = None,
        tags: Optional[List[str]] = None,
        priority: int = 0,
        all_day: bool = True,
        related_policy_ids: Optional[List[str]] = None,
        diagnostic_type: Optional[str] = None
    ):
        self.event_id = event_id
        self.title = title
        self.start_date = start_date
        self.end_date = end_date or start_date
        self.event_type = event_type
        self.description = description
        self.grade = grade
        self.region = region
        self.source = source
        self.url = url
        self.tags = tags or []
        self.priority = priority
        self.all_day = all_day
        self.related_policy_ids = related_policy_ids or []
        self.diagnostic_type = diagnostic_type

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_id": self.event_id,
            "title": self.title,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "event_type": self.event_type,
            "description": self.description,
            "grade": self.grade,
            "region": self.region,
            "source": self.source,
            "url": self.url,
            "tags": self.tags,
            "priority": self.priority,
            "all_day": self.all_day,
            "related_policy_ids": self.related_policy_ids,
            "diagnostic_type": self.diagnostic_type
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalendarEvent":
        """从字典创建事件"""
        return cls(
            event_id=data["event_id"],
            title=data["title"],
            start_date=date.fromisoformat(data["start_date"]),
            end_date=date.fromisoformat(data["end_date"]) if data.get("end_date") else None,
            event_type=data.get("event_type", "general"),
            description=data.get("description", ""),
            grade=data.get("grade"),
            region=data.get("region", "成都"),
            source=data.get("source", "knowledge_base"),
            url=data.get("url"),
            tags=data.get("tags", []),
            priority=data.get("priority", 0),
            all_day=data.get("all_day", True),
            related_policy_ids=data.get("related_policy_ids", []),
            diagnostic_type=data.get("diagnostic_type")
        )


class CalendarService:
    """升学日历服务：从知识库提取关键升学节点，生成结构化日历数据"""

    # 升学事件类型分类
    EVENT_TYPES = {
        "registration": "报名",
        "exam": "考试",
        "result": "出成绩",
        "interview": "面试",
        "enrollment": "录取",
        "deadline": "截止日期",
        "consultation": "咨询会",
        "open_day": "开放日",
        "policy_release": "政策发布",
        "diagnostic": "诊断评估",
        "general": "一般事件"
    }

    # 年级映射
    GRADE_MAP = {
        "幼儿园": "preschool",
        "小学": "primary",
        "初中": "junior",
        "高中": "senior",
        "小升初": "primary_to_junior",
        "初升高": "junior_to_senior",
        "高考": "gaokao"
    }

    # 常见升学关键节点关键词
    KEYWORD_PATTERNS = {
        "registration": [
            r"报名", r"登记", r"填报", r"申请", r"注册"
        ],
        "exam": [
            r"考试", r"测试", r"测评", r"笔试", r"统考"
        ],
        "result": [
            r"成绩", r"结果", r"公布", r"查询", r"放榜"
        ],
        "interview": [
            r"面试", r"面谈", r"面测"
        ],
        "enrollment": [
            r"录取", r"入学", r"报到", r"注册入学"
        ],
        "deadline": [
            r"截止", r"最后", r"逾期"
        ],
        "consultation": [
            r"咨询", r"说明会", r"讲座"
        ],
        "open_day": [
            r"开放日", r"校园开放"
        ],
        "policy_release": [
            r"政策", r"通知", r"公告", r"方案", r"细则"
        ],
        "diagnostic": [
            r"诊断", r"评估", r"测试", r"摸底"
        ]
    }

    def __init__(self, data_dir: Optional[str] = None):
        """
        初始化日历服务
        
        Args:
            data_dir: 数据目录路径，默认为项目根目录下的 data/calendar
        """
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            # 默认路径：项目根目录/data/calendar
            self.data_dir = Path(__file__).parent.parent.parent / "data" / "calendar"
        
        self.events_file = self.data_dir / "events.json"
        self.events: List[CalendarEvent] = []
        self._events_loaded = False
        
        # 确保数据目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载事件数据
        self._load_events()

    def _load_events(self) -> None:
        """从JSON文件加载日历事件数据"""
        try:
            if self.events_file.exists():
                with open(self.events_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                events_data = data.get("events", [])
                self.events = [CalendarEvent.from_dict(event) for event in events_data]
                self._events_loaded = True
                logger.info(f"成功加载 {len(self.events)} 个日历事件")
            else:
                logger.warning(f"日历事件文件不存在: {self.events_file}")
                self.events = []
                self._events_loaded = False
        except json.JSONDecodeError as e:
            logger.error(f"解析日历事件JSON文件失败: {e}")
            self.events = []
            self._events_loaded = False
        except Exception as e:
            logger.error(f"加载日历事件数据失败: {e}")
            self.events = []
            self._events_loaded = False

    def _save_events(self) -> bool:
        """保存日历事件数据到JSON文件"""
        try:
            events_data = {
                "events": [event.to_dict() for event in self.events],
                "updated_at": datetime.now().isoformat()
            }
            
            with open(self.events_file, "w", encoding="utf-8") as f:
                json.dump(events_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"成功保存 {len(self.events)} 个日历事件")
            return True
        except Exception as e:
            logger.error(f"保存日历事件数据失败: {e}")
            return False

    def reload_events(self) -> bool:
        """重新加载日历事件数据"""
        self._load_events()
        return self._events_loaded

    def get_all_events(self) -> List[CalendarEvent]:
        """获取所有日历事件"""
        return self.events

    def get_events_by_date_range(
        self,
        start_date: date,
        end_date: date
    ) -> List[CalendarEvent]:
        """
        根据日期范围获取事件
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            在日期范围内的事件列表
        """
        return [
            event for event in self.events
            if event.start_date <= end_date and event.end_date >= start_date
        ]

    def get_events_by_month(self, year: int, month: int) -> List[CalendarEvent]:
        """
        获取指定月份的事件
        
        Args:
            year: 年份
            month: 月份
        
        Returns:
            该月份的事件列表
        """
        try:
            month_start = date(year, month, 1)
            if month == 12:
                month_end = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(year, month + 1, 1) - timedelta(days=1)
            
            return self.get_events_by_date_range(month_start, month_end)
        except ValueError as e:
            logger.error(f"无效的月份参数: year={year}, month={month}, error={e}")
            return []

    def get_events_by_type(self, event_type: str) -> List[CalendarEvent]:
        """
        根据事件类型获取事件
        
        Args:
            event_type: 事件类型
        
        Returns:
            指定类型的事件列表
        """
        return [event for event in self.events if event.event_type == event_type]

    def get_events_by_grade(self, grade: str) -> List[CalendarEvent]:
        """
        根据年级获取事件
        
        Args:
            grade: 年级标识
        
        Returns:
            指定年级的事件列表
        """
        return [event for event in self.events if event.grade == grade]

    def get_events_by_tag(self, tag: str) -> List[CalendarEvent]:
        """
        根据标签获取事件
        
        Args:
            tag: 标签名称
        
        Returns:
            包含指定标签的事件列表
        """
        return [event for event in self.events if tag in event.tags]

    def get_upcoming_events(
        self,
        days: int = 30,
        max_events: int = 10
    ) -> List[CalendarEvent]:
        """
        获取即将到来的事件
        
        Args:
            days: 未来天数
            max_events: 最大返回事件数
        
        Returns:
            即将到来的事件列表，按日期排序
        """
        today = date.today()
        end_date = today + timedelta(days=days)
        
        upcoming = self.get_events_by_date_range(today, end_date)
        upcoming.sort(key=lambda e: e.start_date)
        
        return upcoming[:max_events]

    def search_events(
        self,
        keyword: str,
        grade: Optional[str] = None,
        event_type: Optional[str] = None,
        region: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[CalendarEvent]:
        """
        搜索事件
        
        Args:
            keyword: 搜索关键词
            grade: 年级过滤
            event_type: 事件类型过滤
            region: 地区过滤
            start_date: 开始日期过滤
            end_date: 结束日期过滤
        
        Returns:
            匹配的事件列表
        """
        results = []
        keyword_lower = keyword.lower()
        
        for event in self.events:
            # 关键词匹配
            if keyword_lower not in event.title.lower() and \
               keyword_lower not in event.description.lower() and \
               not any(keyword_lower in tag.lower() for tag in event.tags):
                continue
            
            # 年级过滤
            if grade and event.grade != grade:
                continue
            
            # 事件类型过滤
            if event_type and event.event_type != event_type:
                continue
            
            # 地区过滤
            if region and event.region != region:
                continue
            
            # 日期范围过滤
            if start_date and event.end_date < start_date:
                continue
            if end_date and event.start_date > end_date:
                continue
            
            results.append(event)
        
        return results

    def get_events_related_to_policy(self, policy_id: str) -> List[CalendarEvent]:
        """
        获取与指定政策相关的事件
        
        Args:
            policy_id: 政策ID
        
        Returns:
            相关事件列表
        """
        return [
            event for event in self.events
            if policy_id in event.related_policy_ids
        ]

    def get_diagnostic_events(self, diagnostic_type: Optional[str] = None) -> List[CalendarEvent]:
        """
        获取诊断评估相关事件
        
        Args:
            diagnostic_type: 诊断类型过滤
        
        Returns:
            诊断事件列表
        """
        if diagnostic_type:
            return [
                event for event in self.events
                if event.event_type == "diagnostic" and event.diagnostic_type == diagnostic_type
            ]
        return [event for event in self.events if event.event_type == "diagnostic"]

    def get_events_by_priority(self, min_priority: int = 0) -> List[CalendarEvent]:
        """
        根据优先级获取事件
        
        Args:
            min_priority: 最低优先级
        
        Returns:
            优先级大于等于指定值的事件列表
        """
        return [event for event in self.events if event.priority >= min_priority]

    def get_event_statistics(self) -> Dict[str, Any]:
        """
        获取事件统计信息
        
        Returns:
            统计信息字典
        """
        stats = {
            "total_events": len(self.events),
            "event_types": defaultdict(int),
            "grades": defaultdict(int),
            "months": defaultdict(int),
            "upcoming_events": 0,
            "past_events": 0
        }
        
        today = date.today()
        
        for event in self.events:
            # 事件类型统计
            stats["event_types"][event.event_type] += 1
            
            # 年级统计
            if event.grade:
                stats["grades"][event.grade] += 1
            
            # 月份统计
            month_key = f"{event.start_date.year}-{event.start_date.month:02d}"
            stats["months"][month_key] += 1
            
            # 时间统计
            if event.start_date >= today:
                stats["upcoming_events"] += 1
            else:
                stats["past_events"] += 1
        
        return dict(stats)

    def add_event(self, event: CalendarEvent) -> bool:
        """
        添加新事件
        
        Args:
            event: 日历事件对象
        
        Returns:
            是否添加成功
        """
        try:
            # 检查事件ID是否已存在
            if any(e.event_id == event.event_id for e in self.events):
                logger.warning(f"事件ID已存在: {event.event_id}")
                return False
            
            self.events.append(event)
            self._save_events()
            return True
        except Exception as e:
            logger.error(f"添加事件失败: {e}")
            return False

    def update_event(self, event_id: str, updated_event: CalendarEvent) -> bool:
        """
        更新事件
        
        Args:
            event_id: 要更新的事件ID
            updated_event: 更新后的事件对象
        
        Returns:
            是否更新成功
        """
        try:
            for i, event in enumerate(self.events):
                if event.event_id == event_id:
                    self.events[i] = updated_event
                    self._save_events()
                    return True
            
            logger.warning(f"未找到要更新的事件: {event_id}")
            return False
        except Exception as e:
            logger.error(f"更新事件失败: {e}")
            return False

    def delete_event(self, event_id: str) -> bool:
        """
        删除事件
        
        Args:
            event_id: 要删除的事件ID
        
        Returns:
            是否删除成功
        """
        try:
            original_count = len(self.events)
            self.events = [event for event in self.events if event.event_id != event_id]
            
            if len(self.events) < original_count:
                self._save_events()
                return True
            
            logger.warning(f"未找到要删除的事件: {event_id}")
            return False
        except Exception as e:
            logger.error(f"删除事件失败: {e}")
            return False

    def classify_event_type(self, title: str, description: str = "") -> str:
        """
        根据标题和描述自动分类事件类型
        
        Args:
            title: 事件标题
            description: 事件描述
        
        Returns:
            事件类型标识
        """
        text = f"{title} {description}"
        
        for event_type, patterns in self.KEYWORD_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return event_type
        
        return "general"

    def extract_grade_from_text(self, text: str) -> Optional[str]:
        """
        从文本中提取年级信息
        
        Args:
            text: 文本内容
        
        Returns:
            年级标识，如果未找到则返回None
        """
        for grade_name, grade_id in self.GRADE_MAP.items():
            if grade_name in text:
                return grade_id
        
        # 尝试匹配年级关键词
        grade_patterns = {
            "preschool": [r"幼儿园", r"学前", r"幼升小"],
            "primary": [r"小学", r"一年级", r"二年级", r"三年级", r"四年级", r"五年级", r"六年级"],
            "junior": [r"初中", r"七年级", r"八年级", r"九年级"],
            "senior": [r"高中", r"高一", r"高二", r"高三"],
            "primary_to_junior": [r"小升初"],
            "junior_to_senior": [r"初升高", r"中考"],
            "gaokao": [r"高考", r"高三"]
        }
        
        for grade_id, patterns in grade_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return grade_id
        
        return None

    def generate_event_id(self, title: str, start_date: date) -> str:
        """
        生成唯一事件ID
        
        Args:
            title: 事件标题
            start_date: 开始日期
        
        Returns:
            生成的事件ID
        """
        # 使用标题的哈希值和日期生成唯一ID
        title_hash = hash(title) & 0xFFFFFF
        date_str = start_date.strftime("%Y%m%d")
        return f"EVT_{date_str}_{title_hash:06X}"

    def create_event_from_text(
        self,
        title: str,
        start_date: date,
        description: str = "",
        end_date: Optional[date] = None,
        **kwargs
    ) -> CalendarEvent:
        """
        从文本信息创建事件
        
        Args:
            title: 事件标题
            start_date: 开始日期
            description: 事件描述
            end_date: 结束日期
            **kwargs: 其他事件属性
        
        Returns:
            创建的日历事件对象
        """
        # 自动分类事件类型
        event_type = self.classify_event_type(title, description)
        
        # 自动提取年级信息
        grade = self.extract_grade_from_text(f"{title} {description}")
        
        # 生成事件ID
        event_id = self.generate_event_id(title, start_date)
        
        return CalendarEvent(
            event_id=event_id,
            title=title,
            start_date=start_date,
            end_date=end_date or start_date,
            event_type=event_type,
            description=description,
            grade=grade or kwargs.get("grade"),
            region=kwargs.get("region", "成都"),
            source=kwargs.get("source", "knowledge_base"),
            url=kwargs.get("url"),
            tags=kwargs.get("tags", []),
            priority=kwargs.get("priority", 0),
            all_day=kwargs.get("all_day", True),
            related_policy_ids=kwargs.get("related_policy_ids", []),
            diagnostic_type=kwargs.get("diagnostic_type")
        )

    def get_calendar_data(
        self,
        year: int,
        month: int,
        grade: Optional[str] = None,
        event_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取日历展示数据
        
        Args:
            year: 年份
            month: 月份
            grade: 年级过滤
            event_type: 事件类型过滤
        
        Returns:
            日历数据字典
        """
        try:
            # 获取月份事件
            month_events = self.get_events_by_month(year, month)
            
            # 应用过滤条件
            if grade:
                month_events = [e for e in month_events if e.grade == grade]
            if event_type:
                month_events = [e for e in month_events if e.event_type == event_type]
            
            # 按日期分组
            events_by_date = defaultdict(list)
            for event in month_events:
                events_by_date[event.start_date.isoformat()].append(event.to_dict())
            
            return {
                "year": year,
                "month": month,
                "total_events": len(month_events),
                "events_by_date": dict(events_by_date),
                "event_types": list(set(e.event_type for e in month_events)),
                "grades": list(set(e.grade for e in month_events if e.grade))
            }
        except Exception as e:
            logger.error(f"获取日历数据失败: {e}")
            return {
                "year": year,
                "month": month,
                "total_events": 0,
                "events_by_date": {},
                "event_types": [],
                "grades": []
            }

    def get_upcoming_deadlines(self, days: int = 7) -> List[CalendarEvent]:
        """
        获取即将到来的截止日期事件
        
        Args:
            days: 未来天数
        
        Returns:
            截止日期事件列表
        """
        today = date.today()
        end_date = today + timedelta(days=days)
        
        return [
            event for event in self.events
            if event.event_type == "deadline" and
            today <= event.start_date <= end_date
        ]

    def get_events_for_diagnostic(
        self,
        grade: str,
        diagnostic_type: str
    ) -> List[CalendarEvent]:
        """
        获取与诊断评估相关的事件
        
        Args:
            grade: 年级
            diagnostic_type: 诊断类型
        
        Returns:
            相关事件列表
        """
        return [
            event for event in self.events
            if event.grade == grade and
            event.diagnostic_type == diagnostic_type
        ]

    def get_policy_related_events(
        self,
        policy_ids: List[str]
    ) -> List[CalendarEvent]:
        """
        获取与多个政策相关的事件
        
        Args:
            policy_ids: 政策ID列表
        
        Returns:
            相关事件列表
        """
        related_events = []
        for event in self.events:
            if any(pid in event.related_policy_ids for pid in policy_ids):
                related_events.append(event)
        return related_events

    def get_events_summary(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """
        获取事件摘要信息
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            事件摘要字典
        """
        events_in_range = self.get_events_by_date_range(start_date, end_date)
        
        summary = {
            "total_events": len(events_in_range),
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "event_types": defaultdict(int),
            "important_events": [],
            "upcoming_deadlines": []
        }
        
        for event in events_in_range:
            # 统计事件类型
            summary["event_types"][event.event_type] += 1
            
            # 收集重要事件（优先级>=5）
            if event.priority >= 5:
                summary["important_events"].append(event.to_dict())
            
            # 收集截止日期事件
            if event.event_type == "deadline":
                summary["upcoming_deadlines"].append(event.to_dict())
        
        summary["event_types"] = dict(summary["event_types"])
        
        return summary
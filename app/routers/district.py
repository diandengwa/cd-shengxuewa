#!/usr/bin/env python3
"""
划片查询API路由 — 成都K12升学参谋
GET /api/district/map 精确到门牌号查询划片数据，速率限制60次/小时
"""

import json
import logging
import time
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, Depends
from pydantic import BaseModel, Field

# ============================================================
# 日志配置
# ============================================================
logger = logging.getLogger("k12.district")

# ============================================================
# 路由定义
# ============================================================
router = APIRouter(
    prefix="/api/district",
    tags=["district"],
    responses={404: {"description": "未找到划片数据"}},
)

# ============================================================
# 速率限制存储（内存实现，生产环境建议使用Redis）
# ============================================================
class RateLimiter:
    """简单的内存速率限制器"""
    
    def __init__(self, max_requests: int = 60, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._store: Dict[str, list] = {}
    
    def check(self, key: str) -> bool:
        """
        检查请求是否允许通过
        返回True表示允许，False表示超过限制
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        # 清理过期记录
        if key in self._store:
            self._store[key] = [t for t in self._store[key] if t > window_start]
        else:
            self._store[key] = []
        
        # 检查是否超过限制
        if len(self._store[key]) >= self.max_requests:
            return False
        
        # 记录本次请求
        self._store[key].append(now)
        return True
    
    def get_remaining(self, key: str) -> int:
        """获取剩余可用请求次数"""
        now = time.time()
        window_start = now - self.window_seconds
        
        if key not in self._store:
            return self.max_requests
        
        # 清理并计算
        self._store[key] = [t for t in self._store[key] if t > window_start]
        return max(0, self.max_requests - len(self._store[key]))

# 全局速率限制器实例
rate_limiter = RateLimiter(max_requests=60, window_seconds=3600)

# ============================================================
# 速率限制装饰器
# ============================================================
def rate_limit(max_requests: int = 60, window_seconds: int = 3600):
    """
    速率限制装饰器
    基于客户端IP进行限制，返回429状态码表示超过限制
    """
    def decorator(func):
        async def wrapper(request: Request, *args, **kwargs):
            # 获取客户端IP
            client_ip = request.client.host if request.client else "unknown"
            # 使用IP作为速率限制的key
            key = f"district_map:{client_ip}"
            
            if not rate_limiter.check(key):
                remaining = rate_limiter.get_remaining(key)
                logger.warning(f"速率限制触发 - IP: {client_ip}, 剩余次数: {remaining}")
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": 429,
                        "message": "请求过于频繁，请稍后再试",
                        "data": {
                            "retry_after_seconds": window_seconds,
                            "remaining_requests": remaining
                        }
                    }
                )
            
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator

# ============================================================
# 数据模型
# ============================================================
class DistrictQueryParams(BaseModel):
    """划片查询参数"""
    address: str = Field(..., description="门牌号地址，例如：成都市锦江区红星路一段35号")
    
    class Config:
        json_schema_extra = {
            "example": {
                "address": "成都市锦江区红星路一段35号"
            }
        }

class DistrictSchool(BaseModel):
    """划片学校信息"""
    school_name: str = Field(..., description="学校名称")
    school_type: str = Field(..., description="学校类型：小学/初中/九年一贯制")
    district: str = Field(..., description="所属行政区")
    address: str = Field(..., description="学校地址")
    phone: Optional[str] = Field(None, description="联系电话")
    website: Optional[str] = Field(None, description="学校网站")
    description: Optional[str] = Field(None, description="学校简介")
    enrollment_plan: Optional[int] = Field(None, description="招生计划人数")
    enrollment_range: Optional[str] = Field(None, description="招生范围描述")

class DistrictQueryResult(BaseModel):
    """划片查询结果"""
    address: str = Field(..., description="查询的地址")
    parsed_address: Dict[str, Any] = Field(..., description="解析后的地址信息")
    schools: List[DistrictSchool] = Field(..., description="划片学校列表")
    query_time: str = Field(..., description="查询时间")
    data_source: str = Field(..., description="数据来源")
    confidence: float = Field(..., description="匹配置信度 0-1")

# ============================================================
# 地址解析工具
# ============================================================
class AddressParser:
    """成都地址解析器"""
    
    # 成都行政区划
    DISTRICTS = [
        "锦江区", "青羊区", "金牛区", "武侯区", "成华区",
        "龙泉驿区", "青白江区", "新都区", "温江区", "双流区",
        "郫都区", "新津区", "都江堰市", "彭州市", "邛崃市",
        "崇州市", "金堂县", "大邑县", "蒲江县", "简阳市",
        "高新区", "天府新区", "东部新区"
    ]
    
    # 街道/镇关键词
    STREET_KEYWORDS = ["街道", "镇", "乡"]
    
    # 路/街/巷关键词
    ROAD_KEYWORDS = ["路", "街", "巷", "大道", "大街", "段"]
    
    @classmethod
    def parse(cls, address: str) -> Dict[str, Any]:
        """
        解析成都地址
        返回结构化地址信息
        """
        result = {
            "original": address,
            "district": None,
            "street": None,
            "road": None,
            "door_number": None,
            "community": None,
            "building": None,
            "unit": None,
            "room": None
        }
        
        if not address:
            return result
        
        # 去除空格
        address = address.strip()
        
        # 提取行政区
        for district in cls.DISTRICTS:
            if district in address:
                result["district"] = district
                address = address.replace(district, "", 1)
                break
        
        # 提取街道/镇
        for keyword in cls.STREET_KEYWORDS:
            match = re.search(rf"([\u4e00-\u9fa5]+{keyword})", address)
            if match:
                result["street"] = match.group(1)
                address = address.replace(match.group(1), "", 1)
                break
        
        # 提取路/街/巷
        for keyword in cls.ROAD_KEYWORDS:
            match = re.search(rf"([\u4e00-\u9fa5\d]+{keyword})", address)
            if match:
                result["road"] = match.group(1)
                address = address.replace(match.group(1), "", 1)
                break
        
        # 提取门牌号
        door_match = re.search(r"(\d+)\s*号", address)
        if door_match:
            result["door_number"] = door_match.group(1)
            address = address.replace(door_match.group(0), "", 1)
        
        # 提取小区/社区
        community_match = re.search(r"([\u4e00-\u9fa5]+(?:小区|社区|苑|园|庭|居|府|城))", address)
        if community_match:
            result["community"] = community_match.group(1)
            address = address.replace(community_match.group(1), "", 1)
        
        # 提取楼栋
        building_match = re.search(r"(\d+)\s*(?:栋|幢|号楼|单元)", address)
        if building_match:
            result["building"] = building_match.group(1)
            address = address.replace(building_match.group(0), "", 1)
        
        # 提取单元
        unit_match = re.search(r"(\d+)\s*单元", address)
        if unit_match:
            result["unit"] = unit_match.group(1)
            address = address.replace(unit_match.group(0), "", 1)
        
        # 提取房间号
        room_match = re.search(r"(\d+)\s*(?:室|号房|户)", address)
        if room_match:
            result["room"] = room_match.group(1)
        
        return result

# ============================================================
# 划片数据加载
# ============================================================
class DistrictDataLoader:
    """划片数据加载器"""
    
    _data: Optional[Dict[str, Any]] = None
    _last_load_time: Optional[float] = None
    _cache_duration: int = 3600  # 缓存1小时
    
    @classmethod
    def get_data_path(cls) -> Path:
        """获取划片数据文件路径"""
        return Path(__file__).parent.parent / "data" / "district_map.json"
    
    @classmethod
    def load_data(cls) -> Dict[str, Any]:
        """
        加载划片数据
        支持缓存，避免频繁读取文件
        """
        now = time.time()
        
        # 检查缓存是否有效
        if cls._data is not None and cls._last_load_time is not None:
            if now - cls._last_load_time < cls._cache_duration:
                return cls._data
        
        data_path = cls.get_data_path()
        
        if not data_path.exists():
            logger.warning(f"划片数据文件不存在: {data_path}")
            # 返回默认空数据
            cls._data = {
                "version": "1.0",
                "update_time": datetime.now().isoformat(),
                "districts": {}
            }
            cls._last_load_time = now
            return cls._data
        
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                cls._data = json.load(f)
            cls._last_load_time = now
            logger.info(f"划片数据加载成功，共 {len(cls._data.get('districts', {}))} 个行政区")
        except Exception as e:
            logger.error(f"划片数据加载失败: {e}")
            cls._data = {
                "version": "1.0",
                "update_time": datetime.now().isoformat(),
                "districts": {}
            }
            cls._last_load_time = now
        
        return cls._data
    
    @classmethod
    def reload_data(cls):
        """强制重新加载数据"""
        cls._data = None
        cls._last_load_time = None
        return cls.load_data()

# ============================================================
# 划片匹配引擎
# ============================================================
class DistrictMatcher:
    """划片匹配引擎"""
    
    @staticmethod
    def match_schools(parsed_address: Dict[str, Any]) -> List[DistrictSchool]:
        """
        根据解析后的地址匹配划片学校
        返回匹配的学校列表
        """
        schools = []
        data = DistrictDataLoader.load_data()
        
        district = parsed_address.get("district")
        if not district:
            logger.warning("地址中未识别到行政区")
            return schools
        
        # 获取该行政区的划片数据
        district_data = data.get("districts", {}).get(district, {})
        if not district_data:
            logger.warning(f"未找到行政区 {district} 的划片数据")
            return schools
        
        # 获取街道/路信息
        street = parsed_address.get("street")
        road = parsed_address.get("road")
        door_number = parsed_address.get("door_number")
        community = parsed_address.get("community")
        
        # 构建匹配键
        match_keys = []
        if street:
            match_keys.append(street)
        if road:
            match_keys.append(road)
        if community:
            match_keys.append(community)
        
        # 如果没有具体地址信息，返回该行政区所有学校
        if not match_keys:
            for school_data in district_data.get("schools", []):
                school = DistrictSchool(**school_data)
                schools.append(school)
            return schools
        
        # 精确匹配
        for school_data in district_data.get("schools", []):
            school = DistrictSchool(**school_data)
            
            # 检查招生范围是否匹配
            enrollment_range = school.enrollment_range or ""
            
            # 检查街道/路匹配
            for key in match_keys:
                if key and key in enrollment_range:
                    if school not in schools:
                        schools.append(school)
                    break
        
        # 如果没有精确匹配，尝试模糊匹配
        if not schools:
            for school_data in district_data.get("schools", []):
                school = DistrictSchool(**school_data)
                enrollment_range = school.enrollment_range or ""
                
                # 检查地址中的关键词是否在招生范围内
                for part in parsed_address.values():
                    if part and isinstance(part, str) and len(part) >= 2:
                        if part in enrollment_range:
                            if school not in schools:
                                schools.append(school)
        
        return schools
    
    @staticmethod
    def calculate_confidence(parsed_address: Dict[str, Any], matched_schools: List[DistrictSchool]) -> float:
        """
        计算匹配置信度
        基于地址解析的完整度和匹配的精确度
        """
        if not matched_schools:
            return 0.0
        
        # 地址解析完整度
        address_parts = [
            parsed_address.get("district"),
            parsed_address.get("street") or parsed_address.get("road"),
            parsed_address.get("door_number"),
            parsed_address.get("community")
        ]
        
        valid_parts = sum(1 for part in address_parts if part)
        total_parts = len(address_parts)
        
        completeness = valid_parts / total_parts if total_parts > 0 else 0
        
        # 匹配精确度
        # 如果有门牌号或小区名，匹配更精确
        has_detail = bool(parsed_address.get("door_number") or parsed_address.get("community"))
        precision = 0.8 if has_detail else 0.5
        
        # 综合置信度
        confidence = (completeness * 0.4 + precision * 0.6)
        
        return min(confidence, 1.0)

# ============================================================
# API端点
# ============================================================
@router.get("/map", response_model=Dict[str, Any])
@rate_limit(max_requests=60, window_seconds=3600)
async def query_district_map(
    request: Request,
    address: str = Query(..., description="门牌号地址，例如：成都市锦江区红星路一段35号")
):
    """
    划片查询API
    根据门牌号地址查询对应的划片学校信息
    """
    logger.info(f"划片查询请求 - 地址: {address}")
    
    # 参数验证
    if not address or len(address.strip()) < 5:
        raise HTTPException(
            status_code=400,
            detail={
                "code": 400,
                "message": "地址参数无效，请输入完整的地址信息（至少5个字符）",
                "data": None
            }
        )
    
    try:
        # 解析地址
        parsed_address = AddressParser.parse(address)
        logger.debug(f"地址解析结果: {parsed_address}")
        
        # 检查是否识别到行政区
        if not parsed_address.get("district"):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": 400,
                    "message": "无法识别地址中的行政区，请确保地址包含成都市行政区名称（如：锦江区、青羊区等）",
                    "data": {
                        "parsed_address": parsed_address
                    }
                }
            )
        
        # 匹配学校
        matched_schools = DistrictMatcher.match_schools(parsed_address)
        
        # 计算置信度
        confidence = DistrictMatcher.calculate_confidence(parsed_address, matched_schools)
        
        # 构建响应
        result = DistrictQueryResult(
            address=address,
            parsed_address=parsed_address,
            schools=matched_schools,
            query_time=datetime.now().isoformat(),
            data_source="成都市教育局官方划片数据",
            confidence=confidence
        )
        
        # 记录查询日志
        logger.info(
            f"划片查询完成 - 地址: {address}, "
            f"匹配学校数: {len(matched_schools)}, "
            f"置信度: {confidence:.2f}"
        )
        
        return {
            "code": 200,
            "message": "查询成功",
            "data": result.model_dump()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"划片查询异常 - 地址: {address}, 错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500,
                "message": "服务器内部错误，请稍后重试",
                "data": None
            }
        )

# ============================================================
# 数据刷新端点
# ============================================================
@router.post("/reload", response_model=Dict[str, Any])
async def reload_district_data(request: Request):
    """
    重新加载划片数据
    管理员接口，用于数据更新后刷新缓存
    """
    logger.info("收到划片数据重新加载请求")
    
    try:
        # 重新加载数据
        data = DistrictDataLoader.reload_data()
        
        district_count = len(data.get("districts", {}))
        school_count = sum(
            len(district.get("schools", []))
            for district in data.get("districts", {}).values()
        )
        
        logger.info(f"划片数据重新加载成功 - 行政区数: {district_count}, 学校数: {school_count}")
        
        return {
            "code": 200,
            "message": "数据重新加载成功",
            "data": {
                "district_count": district_count,
                "school_count": school_count,
                "version": data.get("version", "unknown"),
                "update_time": data.get("update_time", datetime.now().isoformat())
            }
        }
        
    except Exception as e:
        logger.error(f"划片数据重新加载失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500,
                "message": "数据重新加载失败",
                "data": None
            }
        )

# ============================================================
# 健康检查端点
# ============================================================
@router.get("/health", response_model=Dict[str, Any])
async def health_check():
    """划片查询服务健康检查"""
    try:
        data = DistrictDataLoader.load_data()
        district_count = len(data.get("districts", {}))
        
        return {
            "code": 200,
            "message": "服务正常",
            "data": {
                "status": "healthy",
                "district_count": district_count,
                "data_version": data.get("version", "unknown"),
                "data_update_time": data.get("update_time", "unknown"),
                "cache_expire_in": DistrictDataLoader._cache_duration
            }
        }
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "code": 500,
            "message": "服务异常",
            "data": {
                "status": "unhealthy",
                "error": str(e)
            }
        }
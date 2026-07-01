#!/usr/bin/env python3
"""
划片查询服务层：加载 districting_2025.json 数据，实现门牌号精确匹配和模糊搜索
支持从RAG知识库获取补充数据，实现政策查询+诊断一站式服务
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent


class DistrictService:
    """划片查询服务类"""

    def __init__(self, data_path: Optional[Path] = None, rag_service: Optional[Any] = None):
        """
        初始化划片查询服务

        Args:
            data_path: districting_2025.json 文件路径，默认为项目 data 目录
            rag_service: RAG知识库服务实例，用于补充查询数据
        """
        if data_path is None:
            data_path = PROJECT_ROOT / "data" / "districting_2025.json"
        self.data_path = data_path
        self._data: Dict[str, Any] = {}
        self._loaded = False
        self._rag_service = rag_service
        self._load_data()

    def _load_data(self) -> None:
        """加载划片数据"""
        try:
            if not self.data_path.exists():
                logger.warning(f"划片数据文件不存在: {self.data_path}")
                self._data = {}
                self._loaded = False
                return

            with open(self.data_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            self._loaded = True
            logger.info(f"成功加载划片数据: {self.data_path}，共 {len(self._data)} 条记录")
        except json.JSONDecodeError as e:
            logger.error(f"划片数据文件格式错误: {e}")
            self._data = {}
            self._loaded = False
        except Exception as e:
            logger.error(f"加载划片数据失败: {e}")
            self._data = {}
            self._loaded = False

    def reload(self) -> bool:
        """重新加载数据"""
        self._load_data()
        return self._loaded

    @property
    def is_loaded(self) -> bool:
        """数据是否已加载"""
        return self._loaded

    @property
    def data(self) -> Dict[str, Any]:
        """获取原始数据"""
        return self._data

    def _normalize_address(self, address: str) -> str:
        """
        标准化地址：去除空格、全角转半角、统一大小写

        Args:
            address: 原始地址

        Returns:
            标准化后的地址
        """
        if not address:
            return ""
        # 去除前后空格
        address = address.strip()
        # 全角转半角
        address = address.replace("，", ",").replace("。", ".").replace("（", "(").replace("）", ")")
        address = address.replace("　", " ").replace("—", "-").replace("－", "-")
        # 统一大小写
        address = address.upper()
        # 去除多余空格
        address = re.sub(r"\s+", "", address)
        return address

    def _extract_house_number(self, address: str) -> Optional[str]:
        """
        从地址中提取门牌号

        Args:
            address: 地址字符串

        Returns:
            提取的门牌号，如果没有则返回 None
        """
        if not address:
            return None

        # 匹配门牌号模式：数字+号/栋/单元/楼
        patterns = [
            r"(\d+[号栋单元楼])",
            r"(\d+[-—]\d+[号栋单元楼])",
            r"(\d+[号栋单元楼]\d+[号室])",
            r"(\d+[号栋单元楼]\d+[-—]\d+[号室])",
        ]

        for pattern in patterns:
            match = re.search(pattern, address)
            if match:
                return match.group(1)

        # 尝试匹配纯数字门牌号
        match = re.search(r"(\d+)", address)
        if match:
            return match.group(1)

        return None

    def _match_exact(self, address: str) -> Optional[Dict[str, Any]]:
        """
        精确匹配门牌号

        Args:
            address: 地址字符串

        Returns:
            匹配到的划片信息，如果没有匹配则返回 None
        """
        if not self._loaded or not address:
            return None

        normalized = self._normalize_address(address)
        house_number = self._extract_house_number(normalized)

        if not house_number:
            return None

        # 遍历所有划片区域进行精确匹配
        for district_key, district_info in self._data.items():
            if not isinstance(district_info, dict):
                continue

            # 检查该区域的门牌号列表
            house_numbers = district_info.get("house_numbers", [])
            if not isinstance(house_numbers, list):
                continue

            # 标准化门牌号列表
            normalized_numbers = [self._normalize_address(h) for h in house_numbers]

            # 精确匹配
            if house_number in normalized_numbers:
                return {
                    "district": district_key,
                    "school": district_info.get("school", ""),
                    "address_range": district_info.get("address_range", ""),
                    "house_number": house_number,
                    "match_type": "exact",
                    "details": district_info
                }

        return None

    def _match_fuzzy(self, address: str) -> List[Dict[str, Any]]:
        """
        模糊匹配门牌号

        Args:
            address: 地址字符串

        Returns:
            匹配到的划片信息列表，按匹配度排序
        """
        if not self._loaded or not address:
            return []

        normalized = self._normalize_address(address)
        results = []

        # 遍历所有划片区域进行模糊匹配
        for district_key, district_info in self._data.items():
            if not isinstance(district_info, dict):
                continue

            # 检查该区域的门牌号列表
            house_numbers = district_info.get("house_numbers", [])
            if not isinstance(house_numbers, list):
                continue

            # 检查地址范围
            address_range = district_info.get("address_range", "")
            if address_range and normalized in self._normalize_address(address_range):
                results.append({
                    "district": district_key,
                    "school": district_info.get("school", ""),
                    "address_range": address_range,
                    "house_number": None,
                    "match_type": "fuzzy_range",
                    "details": district_info,
                    "score": 0.8
                })
                continue

            # 检查门牌号是否包含在地址中
            for house_num in house_numbers:
                normalized_house = self._normalize_address(house_num)
                if normalized_house and (normalized_house in normalized or normalized in normalized_house):
                    results.append({
                        "district": district_key,
                        "school": district_info.get("school", ""),
                        "address_range": address_range,
                        "house_number": house_num,
                        "match_type": "fuzzy_house",
                        "details": district_info,
                        "score": 0.6
                    })
                    break

        # 按匹配度排序
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results

    def query(self, address: str, use_rag: bool = True) -> Dict[str, Any]:
        """
        查询地址对应的划片信息

        Args:
            address: 地址字符串
            use_rag: 是否使用RAG知识库补充数据

        Returns:
            查询结果，包含匹配信息和补充数据
        """
        if not address:
            return {
                "success": False,
                "error": "地址不能为空",
                "matches": [],
                "rag_data": None
            }

        # 先尝试精确匹配
        exact_match = self._match_exact(address)
        matches = []

        if exact_match:
            matches.append(exact_match)
        else:
            # 精确匹配失败，尝试模糊匹配
            fuzzy_matches = self._match_fuzzy(address)
            matches.extend(fuzzy_matches)

        # 构建结果
        result = {
            "success": True,
            "query_address": address,
            "matches": matches,
            "match_count": len(matches),
            "rag_data": None
        }

        # 如果启用RAG，获取补充数据
        if use_rag and self._rag_service:
            try:
                rag_data = self._rag_service.query(address)
                result["rag_data"] = rag_data
            except Exception as e:
                logger.error(f"获取RAG数据失败: {e}")
                result["rag_data"] = None

        return result

    def get_district_info(self, district_name: str) -> Optional[Dict[str, Any]]:
        """
        获取指定区域的信息

        Args:
            district_name: 区域名称

        Returns:
            区域信息，如果不存在则返回 None
        """
        if not self._loaded:
            return None

        # 直接匹配
        if district_name in self._data:
            return self._data[district_name]

        # 模糊匹配
        for key, value in self._data.items():
            if district_name in key or key in district_name:
                return value

        return None

    def get_all_districts(self) -> List[str]:
        """
        获取所有区域名称列表

        Returns:
            区域名称列表
        """
        if not self._loaded:
            return []
        return list(self._data.keys())

    def get_schools_by_district(self, district_name: str) -> List[str]:
        """
        获取指定区域对应的学校列表

        Args:
            district_name: 区域名称

        Returns:
            学校名称列表
        """
        district_info = self.get_district_info(district_name)
        if not district_info:
            return []

        schools = district_info.get("schools", [])
        if isinstance(schools, list):
            return schools
        elif isinstance(schools, str):
            return [schools]
        return []

    def get_house_numbers_by_district(self, district_name: str) -> List[str]:
        """
        获取指定区域的门牌号列表

        Args:
            district_name: 区域名称

        Returns:
            门牌号列表
        """
        district_info = self.get_district_info(district_name)
        if not district_info:
            return []

        house_numbers = district_info.get("house_numbers", [])
        if isinstance(house_numbers, list):
            return house_numbers
        return []

    def search_by_school(self, school_name: str) -> List[Dict[str, Any]]:
        """
        根据学校名称搜索划片区域

        Args:
            school_name: 学校名称

        Returns:
            匹配的划片区域列表
        """
        if not self._loaded or not school_name:
            return []

        results = []
        normalized_school = self._normalize_address(school_name)

        for district_key, district_info in self._data.items():
            if not isinstance(district_info, dict):
                continue

            school = district_info.get("school", "")
            if school and normalized_school in self._normalize_address(school):
                results.append({
                    "district": district_key,
                    "school": school,
                    "address_range": district_info.get("address_range", ""),
                    "house_numbers": district_info.get("house_numbers", []),
                    "details": district_info
                })

        return results

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取划片数据统计信息

        Returns:
            统计信息字典
        """
        if not self._loaded:
            return {
                "total_districts": 0,
                "total_schools": 0,
                "total_house_numbers": 0,
                "loaded": False
            }

        total_schools = set()
        total_house_numbers = 0

        for district_info in self._data.values():
            if not isinstance(district_info, dict):
                continue

            # 统计学校
            school = district_info.get("school", "")
            if school:
                total_schools.add(school)

            # 统计门牌号
            house_numbers = district_info.get("house_numbers", [])
            if isinstance(house_numbers, list):
                total_house_numbers += len(house_numbers)

        return {
            "total_districts": len(self._data),
            "total_schools": len(total_schools),
            "total_house_numbers": total_house_numbers,
            "loaded": True
        }

    def validate_address(self, address: str) -> Dict[str, Any]:
        """
        验证地址格式并返回解析结果

        Args:
            address: 地址字符串

        Returns:
            验证结果，包含解析后的地址信息
        """
        if not address:
            return {
                "valid": False,
                "error": "地址不能为空",
                "parsed": None
            }

        try:
            normalized = self._normalize_address(address)
            house_number = self._extract_house_number(normalized)

            return {
                "valid": True,
                "original": address,
                "normalized": normalized,
                "house_number": house_number,
                "has_house_number": house_number is not None,
                "parsed": {
                    "full_address": normalized,
                    "house_number": house_number
                }
            }
        except Exception as e:
            logger.error(f"地址验证失败: {e}")
            return {
                "valid": False,
                "error": f"地址解析失败: {str(e)}",
                "parsed": None
            }
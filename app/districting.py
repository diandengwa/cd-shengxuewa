"""
划片查询模块
加载 districting_2025.json，提供地址→学校 模糊搜索
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class SchoolDistrict:
    school_name: str
    district: str
    school_level: str  # 小学/初中
    coverage_area: str
    source: str


# 全局缓存
_schools: List[SchoolDistrict] = []
_loaded = False


def load():
    """加载划片数据"""
    global _schools, _loaded
    data_path = PROJECT_ROOT / "districting_2025.json"
    if not data_path.exists():
        _loaded = False
        return False
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _schools = [
            SchoolDistrict(
                school_name=s["school_name"],
                district=s["district"],
                school_level=s["school_level"],
                coverage_area=s["coverage_area"],
                source=s.get("source", ""),
            )
            for s in data.get("schools", [])
        ]
        _loaded = True
        return True
    except Exception:
        _loaded = False
        return False


def is_loaded() -> bool:
    return _loaded


def _extract_keywords(text: str) -> List[str]:
    """从地址中提取关键词（去噪）"""
    # 去掉数字、门牌号、常见无意义后缀
    text = re.sub(r'\d+', '', text)
    text = re.sub(r'[号栋单元楼层室座]', '', text)
    # 按标点和空格分词
    parts = re.split(r'[,，、\s]+', text)
    # 过滤太短的词
    return [p.strip() for p in parts if len(p.strip()) >= 2]


def search(address: str, district: str = None, level: str = None) -> List[Dict]:
    """
    根据地址搜索对口学校

    Args:
        address: 用户输入地址（如「泡桐树街33号」「中和镇」）
        district: 可选，限定区域（如「青羊区」）
        level: 可选，限定学段（「小学」或「初中」）

    Returns:
        匹配的学校列表
    """
    if not _loaded or not address:
        return []

    keywords = _extract_keywords(address)
    if not keywords:
        # 关键词提取失败，回退到全量匹配
        keywords = [address]

    results = []
    for school in _schools:
        # 区域过滤
        if district and school.district != district:
            continue
        # 学段过滤
        if level and school.school_level != level:
            continue

        # 计算匹配分数
        score = 0
        coverage = school.coverage_area
        name = school.school_name

        for kw in keywords:
            # 地址在 coverage_area 中命中 → 高权重
            if kw in coverage:
                score += 10
            # 地址在学校名中命中
            if kw in name:
                score += 5
            # 区域名命中
            if kw in school.district:
                score += 3

        if score > 0:
            results.append({
                "school_name": school.school_name,
                "district": school.district,
                "school_level": school.school_level,
                "coverage_area": school.coverage_area,
                "source": school.source,
                "score": score,
            })

    # 按分数降序
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def list_all(district: str = None, level: str = None) -> List[Dict]:
    """列出所有学校（支持筛选）"""
    if not _loaded:
        return []
    results = []
    for school in _schools:
        if district and school.district != district:
            continue
        if level and school.school_level != level:
            continue
        results.append({
            "school_name": school.school_name,
            "district": school.district,
            "school_level": school.school_level,
            "coverage_area": school.coverage_area,
            "source": school.source,
        })
    return results

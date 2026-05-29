"""
数据加载器 v2.0
复用v1 Wiki加载 + 新增GT校准库/执行温差库/历史摇号数据库
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
BUILD_DIR = PROJECT_ROOT / "build"
WIKI_DIR = PROJECT_ROOT / "wiki"
DATA_DIR = PROJECT_ROOT / "data"


class WikiLoader:
    """Wiki 数据加载器 — 复用v1"""

    def __init__(self):
        self.manifest: List[dict] = []
        self.search_index: Dict = {}
        self._loaded = False

    def load(self) -> bool:
        manifest_path = BUILD_DIR / "manifest.json"
        index_path = BUILD_DIR / "search_index.json"
        if not manifest_path.exists() or not index_path.exists():
            return False
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                self.manifest = json.load(f)
            with open(index_path, 'r', encoding='utf-8') as f:
                self.search_index = json.load(f)
            self._loaded = True
            return True
        except (json.JSONDecodeError, IOError):
            return False

    def is_loaded(self) -> bool:
        return self._loaded

    def get_page_content(self, path: str) -> Optional[str]:
        page_path = PROJECT_ROOT / path
        if not page_path.exists():
            return None
        try:
            with open(page_path, 'r', encoding='utf-8') as f:
                return f.read()
        except IOError:
            return None

    def get_page_info(self, path: str) -> Optional[dict]:
        for entry in self.manifest:
            if entry.get("path") == path:
                return entry
        return None

    def list_pages_by_type(self, page_type: str) -> List[str]:
        return self.search_index.get("by_type", {}).get(page_type, [])

    def list_pages_by_keyword(self, keyword: str) -> List[str]:
        return self.search_index.get("by_keyword", {}).get(keyword, [])

    def get_all_keywords(self) -> List[str]:
        return list(self.search_index.get("by_keyword", {}).keys())


class GroundTruthLoader:
    """Ground Truth 校准库 — L2数据层"""

    def __init__(self):
        self.records: List[dict] = []
        self._loaded = False

    def load(self) -> bool:
        gt_path = DATA_DIR / "ground_truth.json"
        if not gt_path.exists():
            self._loaded = True  # 允许空库
            return True
        try:
            with open(gt_path, 'r', encoding='utf-8') as f:
                self.records = json.load(f)
            self._loaded = True
            return True
        except (json.JSONDecodeError, IOError):
            return False

    def is_loaded(self) -> bool:
        return self._loaded

    def validate(self, claim: str, context: str = "") -> dict:
        """校准一个声明，返回{verified, confidence, correction, source, fact} """
        # 多策略匹配：1.关键词精确匹配 2.类别+片段匹配 3.常见错误匹配
        best_match = None
        best_score = 0

        full_text = (claim + " " + context).lower()

        for record in self.records:
            score = 0
            keyword = record.get("keyword", "")
            category = record.get("category", "")
            common_error = record.get("common_error", "")

            # 关键词精确匹配（最高优先级）
            if keyword and keyword in full_text:
                score += 3

            # 常见错误匹配（检测到错误说法时，给高分触发纠错）
            if common_error and common_error in full_text:
                score += 5  # 纠错比确认更重要

            # 类别匹配（弱信号）
            if category and category in full_text:
                score += 1

            # fact中的关键片段匹配
            fact = record.get("fact", "")
            fact_fragments = [f for f in fact.split("，") if len(f) >= 4]
            for frag in fact_fragments:
                if frag in full_text:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = record

        if best_match and best_score >= 2:
            return {
                "verified": True,
                "confidence": best_match.get("confidence", "🟡"),
                "correction": best_match.get("correction", ""),
                "source": best_match.get("source", ""),
                "fact": best_match.get("fact", ""),
                "common_error": best_match.get("common_error", ""),
            }
        return {"verified": None, "confidence": "🟡", "correction": "", "source": "", "fact": "", "common_error": ""}

    def get_records_by_category(self, category: str) -> list:
        """按类别获取GT记录"""
        return [r for r in self.records if r.get("category") == category]

    def get_all_categories(self) -> list:
        """获取所有GT类别"""
        return list(set(r.get("category", "") for r in self.records if r.get("category")))


class LotteryDataLoader:
    """历史摇号数据库"""

    def __init__(self):
        self.data: List[dict] = []
        self._loaded = False

    def load(self) -> bool:
        path = DATA_DIR / "lottery_history.json"
        if not path.exists():
            self._loaded = True
            return True
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            self._loaded = True
            return True
        except (json.JSONDecodeError, IOError):
            return False

    def is_loaded(self) -> bool:
        return self._loaded

    def get_school_history(self, school_name: str) -> List[dict]:
        """获取某校历史摇号数据"""
        return [r for r in self.data if school_name in r.get("school", "")]

    def get_competition_level(self, school_name: str) -> dict:
        """获取竞争烈度评估"""
        history = self.get_school_history(school_name)
        if not history:
            return {"level": "未知", "data_available": False}

        latest = history[-1] if history else {}
        rate = latest.get("rate", 0)
        if isinstance(rate, str):
            rate = float(rate.replace("%", "")) / 100

        if rate < 0.03:
            level = "🔥🔥🔥🔥🔥"
            label = "极度激烈"
        elif rate < 0.08:
            level = "🔥🔥🔥🔥"
            label = "激烈"
        elif rate < 0.20:
            level = "🔥🔥🔥"
            label = "中等"
        else:
            level = "🔥🔥"
            label = "相对宽松"

        return {
            "level": level,
            "label": label,
            "latest_rate": rate,
            "data_available": True,
            "year": latest.get("year", ""),
            "note": "基于历史数据评估，2024年后官方不再汇总公布中签率",
        }


# 全局实例
wiki_loader = WikiLoader()
gt_loader = GroundTruthLoader()
lottery_loader = LotteryDataLoader()

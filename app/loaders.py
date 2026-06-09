"""
数据加载器 v2.0
复用v1 Wiki加载 + 新增GT校准库/执行温差库/历史摇号数据库
"""

import os
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
        best_match = None
        best_score = 0

        full_text = (claim + " " + context).lower()

        for record in self.records:
            score = 0
            keyword = record.get("keyword", "")
            category = record.get("category", "")
            common_error = record.get("common_error", "")

            # 关键词精确匹配
            if keyword and keyword in full_text:
                score += 3

            # 常见错误匹配
            if common_error and common_error in full_text:
                score += 5

            # 类别匹配
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
        return [r for r in self.records if r.get("category") == category]

    def get_all_categories(self) -> list:
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
        return [r for r in self.data if school_name in r.get("school", "")]

    def get_competition_level(self, school_name: str) -> dict:
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


class KnowledgeCardLoader:
    """Dual-core knowledge base card loader."""

    def __init__(self):
        self.golden_cards = []  # type: List[dict]
        self.problem_cards = []  # type: List[dict]
        self._loaded = False
        self.kb_root = Path(os.getenv(
            "KNOWLEDGE_BASE_DIR",
            str(Path(__file__).parent.parent.parent / "opc-agent-knowledge")
        ))

    def load(self):
        # type: () -> bool
        golden_dir = self.kb_root / "0-golden-interpretations"
        problems_dir = self.kb_root / "0-problems"
        loaded_any = False
        if golden_dir.exists():
            self.golden_cards = self._load_json_cards(golden_dir)
            loaded_any = True
        if problems_dir.exists():
            self.problem_cards = self._load_json_cards(problems_dir)
            loaded_any = True
        self._loaded = loaded_any
        return self._loaded

    def _load_json_cards(self, directory):
        # type: (Path) -> List[dict]
        cards = []
        for fpath in sorted(directory.glob("*.json")):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    card = json.load(f)
                if isinstance(card, dict) and card.get("id"):
                    cards.append(card)
            except (json.JSONDecodeError, IOError):
                continue
        return cards

    def is_loaded(self):
        # type: () -> bool
        return self._loaded

    def search_golden(self, keywords, category="",
                      academic_year=None, status=None,
                      max_cards=10):
        # type: (List[str], str, Optional[int], Optional[str], int) -> List[dict]
        scored_cards = []
        kw_lower = [k.lower() for k in keywords]
        
        # 排除通用高频停用词，提升精细匹配度
        stop_words = {"小学", "初中", "高中", "入学", "升学", "学校", "成都", "成都市", "对口"}
        effective_kws = [k for k in kw_lower if k not in stop_words and len(k) > 1]
        
        for card in self.golden_cards:
            if status and card.get("status") != status:
                continue
            if academic_year and card.get("academic_year") != academic_year:
                continue
            if category and card.get("category") != category:
                continue
                
            card_text = self._card_to_text(card).lower()
            
            # 相关性评分：有效词加权
            score = 0
            for kw in kw_lower:
                if kw in card_text:
                    score += 5 if kw in effective_kws else 1
                    
            if score > 0:
                scored_cards.append((score, card))
                
        # 解析年份辅助函数，确保以卡片出台/发布年份作为第一关键字进行排序
        def _get_card_year(c):
            ay = c.get("academic_year")
            if isinstance(ay, int) or (isinstance(ay, str) and ay.isdigit()):
                return int(ay)
            y = c.get("year")
            if isinstance(y, int) or (isinstance(y, str) and y.isdigit()):
                return int(y)
            pd = c.get("publish_date")
            if pd and len(pd) >= 4 and pd[:4].isdigit():
                return int(pd[:4])
            return 0

        # 按卡片出台年份（第一关键字）和相关性得分（第二关键字）降序排序
        scored_cards.sort(key=lambda x: (_get_card_year(x[1]), x[0]), reverse=True)
        return [card for score, card in scored_cards[:max_cards]]

    def search_problems(self, keywords, anxiety_min=1, anxiety_max=5,
                        max_cards=5):
        # type: (List[str], int, int, int) -> List[dict]
        scored_cards = []
        kw_lower = [k.lower() for k in keywords]
        stop_words = {"小学", "初中", "高中", "入学", "升学", "学校", "成都", "成都市", "对口"}
        effective_kws = [k for k in kw_lower if k not in stop_words and len(k) > 1]
        
        for card in self.problem_cards:
            card_text = self._card_to_text(card).lower()
            anxiety = card.get("anxiety_level", 3)
            if anxiety_min <= anxiety <= anxiety_max:
                score = 0
                for kw in kw_lower:
                    if kw in card_text:
                        score += 5 if kw in effective_kws else 1
                if score > 0:
                    scored_cards.append((score, card))
                    
        scored_cards.sort(key=lambda x: x[0], reverse=True)
        return [card for score, card in scored_cards[:max_cards]]

    def get_districting_cards(self, school_name="", max_cards=10):
        # type: (str, int) -> List[dict]
        results = []
        for card in self.golden_cards:
            card_text = self._card_to_text(card).lower()
            category = card.get("category", "")
            card_type = card.get("type", "")
            if "districting" in card_type or "districting" in category or "school" in category:
                if not school_name or school_name.lower() in card_text:
                    results.append(card)
                    if len(results) >= max_cards:
                        break
        return results

    def get_context_text(self, question, scenario="", max_chars=8000):
        # type: (str, str, int) -> str
        import re
        context_parts = []
        total_chars = 0
        raw = re.findall(r'[\u4e00-\u9fff]+', question)
        keywords = []
        for token in raw:
            if len(token) <= 4:
                keywords.append(token)
            else:
                for n in range(2, 5):
                    for i in range(len(token) - n + 1):
                        keywords.append(token[i:i+n])
        keywords = list(dict.fromkeys(keywords))
        if not keywords:
            return ""
            
        golden_cards = self.search_golden(keywords=keywords, max_cards=8)
        for card in golden_cards:
            card_text = self._format_golden_card(card)
            if total_chars + len(card_text) > max_chars:
                break
            context_parts.append(card_text)
            total_chars += len(card_text)
            
        if any(k in scenario for k in ["primary", "transfer", "exam", "小升初", "幼升小"]):
            problem_cards = self.search_problems(keywords=keywords, max_cards=3)
            for card in problem_cards:
                card_text = self._format_problem_card(card)
                if total_chars + len(card_text) > max_chars:
                    break
                context_parts.append(card_text)
                total_chars += len(card_text)
                
        if any(k in question for k in ["districting", "boundary", "school zone", "划片", "学区", "对口", "入学范围"]):
            school_name = ""
            m = re.search(r"([\u4e00-\u9fff]{2,15}(?:小学|初中|高中|中学|学校))", question)
            if m:
                school_name = m.group(1)
            else:
                for short_name in ["泡小", "实小", "龙江路", "泡桐树", "七中育才", "树德小学", "石室联中", "树德实验", "七中初中", "棕北中学"]:
                    if short_name in question:
                        school_name = short_name
                        break
            district_cards = self.get_districting_cards(school_name=school_name, max_cards=6)
            for card in district_cards:
                card_text = self._format_golden_card(card)
                if total_chars + len(card_text) > max_chars:
                    break
                if card_text not in context_parts:
                    context_parts.append(card_text)
                    total_chars += len(card_text)
                    
        return "\n\n---\n\n".join(context_parts) if context_parts else ""

    def _format_golden_card(self, card):
        # type: (dict) -> str
        parts = []
        title = card.get("title", "")
        if not title and card.get("school_name"):
            title = "%s 划片范围" % card.get("school_name")

        year = card.get("academic_year", "")
        status_val = card.get("status", "active")
        source = card.get("source", "")
        category = card.get("category", "")
        header = "### [%s] %s" % (status_val, title)
        if year:
            header += " (%s)" % year
        if source:
            header += " - %s" % source
        parts.append(header)
        if category:
            parts.append("Category: %s" % category)

        # Output specialized attributes for districting cards
        if card.get("school_name"):
            parts.append("School Name: %s" % card.get("school_name"))
        if card.get("district"):
            parts.append("District: %s" % card.get("district"))
        if card.get("school_level"):
            parts.append("School Level: %s" % card.get("school_level"))
        if card.get("coverage_area"):
            parts.append("Coverage Area: %s" % card.get("coverage_area"))

        fact_points = card.get("fact_points", [])
        if fact_points:
            parts.append("Fact points:")
            for fp in fact_points:
                parts.append("  - %s" % fp)
        rules = card.get("rules", [])
        if rules:
            parts.append("Rules:")
            for r in rules:
                parts.append("  - %s" % r)
        historical_ref = card.get("historical_ref")
        if historical_ref:
            parts.append("Historical ref: %s" % historical_ref)
        if card.get("notes"):
            parts.append("Notes: %s" % card.get("notes"))
        return "\n".join(parts)

    def _format_problem_card(self, card):
        # type: (dict) -> str
        parts = []
        parts.append("### Pain point: %s" % card.get("extracted_problem", ""))
        parts.append("Source: %s" % card.get("source_platform", "unknown"))
        parts.append("Anxiety: L%s" % card.get("anxiety_level", 3))
        raw = card.get("raw_expression", "")
        if raw:
            parts.append("Quote: \"%s\"" % raw)
        policies = card.get("associated_policies", [])
        if policies:
            parts.append("Related policies: %s" % ", ".join(policies))
        return "\n".join(parts)

    @staticmethod
    def _card_to_text(card):
        # type: (dict) -> str
        parts = []
        for v in card.values():
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, list):
                parts.extend([str(item) for item in v])
        return " ".join(parts)


# 全局实例
wiki_loader = WikiLoader()
gt_loader = GroundTruthLoader()
lottery_loader = LotteryDataLoader()
knowledge_card_loader = KnowledgeCardLoader()

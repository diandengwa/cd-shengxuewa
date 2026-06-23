#!/usr/bin/env python3
"""
黑话翻译服务层 — 维护升学术语-通俗翻译映射表，支持RAG增强翻译

功能：
1. 基础术语映射（静态字典 + 数据库持久化）
2. RAG增强翻译：基于关键词匹配 + 上下文语义相似度（简单向量化）
3. 翻译历史记录与热度统计
4. 支持管理员动态增删改术语

所属模块：app.services.jargon_service
"""

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# 尝试导入项目配置，若失败则使用默认值
try:
    from app.core.config import settings
except ImportError:
    settings = None

logger = logging.getLogger(__name__)

# ============================================================
# 默认术语映射表（静态兜底，数据库未初始化时使用）
# ============================================================
DEFAULT_JARGON_MAP: Dict[str, str] = {
    "划片": "根据户籍地址划分到对应小学/初中就读",
    "多校划片": "一个小区对应多所学校，通过电脑随机派位确定最终学校",
    "单校划片": "一个小区只对应一所学校，直接入学",
    "大摇号": "成都市直属学校（如四七九中）面向全市的随机派位录取方式",
    "小摇号": "区属学校面向本区的随机派位录取方式",
    "民办摇号": "民办学校报名人数超过招生计划时，通过电脑随机派位录取",
    "直升": "一贯制学校内部，小学毕业生直接升入本校初中部",
    "指标到校": "重点高中将部分招生名额分配到初中学校，由初中推荐优秀学生",
    "调招": "调剂招生，指未被第一志愿录取的学生进入调剂环节",
    "统招": "统一招生，按分数和志愿正常录取",
    "择校": "家长主动选择非划片学校，通常需缴纳择校费",
    "学区房": "位于优质学校划片范围内的房产",
    "学位预警": "某学校划片范围内适龄儿童人数超过招生计划，发布预警提示",
    "六年一学位": "一套房产在六年内只提供一个小学学位（同一家庭子女除外）",
    "两个一致": "适龄儿童户籍与法定监护人户籍一致，户籍地址与实际居住地一致",
    "随迁子女": "随父母在非户籍所在地居住的适龄儿童，需办理居住证等材料",
    "集体户": "户籍挂靠在单位或人才市场的家庭，子女入学需按政策统筹安排",
    "统筹安排": "教育部门根据学位情况统一安排入学，不一定在划片学校",
    "借读": "学生学籍在A校，实际在B校就读（政策收紧，已基本取消）",
    "转学": "学生从一所学校转入另一所学校就读",
    "休学": "学生因健康等原因暂停学业，保留学籍",
    "复学": "休学期满后恢复学业",
    "缓学": "适龄儿童因特殊情况推迟入学年龄",
    "免试入学": "义务教育阶段不举行任何形式的考试选拔学生",
    "就近入学": "按照户籍地址就近安排入学，并非绝对最近距离",
    "公民同招": "公办学校和民办学校同步招生，避免提前掐尖",
    "锁区": "民办学校主要面向本区招生，跨区招生比例受限",
    "补录": "招生录取结束后，未完成招生计划的学校进行补充录取",
    "分班考试": "新生入学后进行的摸底考试，用于均衡分班或实验班选拔",
    "实验班": "学校设立的课程改革试点班级，通常教学进度较快",
    "平行班": "按成绩均衡分配的普通班级",
    "火箭班": "部分学校设立的超常班，教学进度和难度远超普通班",
    "基地班": "与高校或科研机构合作设立的特色班级",
    "国际班": "开设国际课程、面向出国留学的班级",
    "中职": "中等职业学校，包括职业高中、中专、技校",
    "普高": "普通高级中学，以升学为主要目标",
    "职普融通": "职业教育和普通教育相互渗透，学生可互转",
    "综合高中": "同时开设普高课程和职教课程的高中",
    "五年一贯制": "初中毕业后直接进入高职院校，连续学习五年获得大专文凭",
    "3+2": "中职3年+高职2年，分段培养获得大专文凭",
    "3+4": "中职3年+本科4年，分段培养获得本科文凭（部分省份试点）",
    "强基计划": "高校选拔基础学科拔尖学生的特殊招生方式",
    "综合评价": "高校依据高考成绩+校测成绩+综合素质评价进行录取",
    "专项计划": "面向农村和贫困地区的定向招生计划",
    "提前批": "在普通批次之前录取的院校和专业",
    "平行志愿": "考生可填报多个志愿，按分数优先原则依次检索",
    "顺序志愿": "按志愿先后顺序投档，第一志愿优先",
    "滑档": "考生分数未达到所填报任何志愿的投档线",
    "退档": "考生档案被投档后因不符合专业要求等原因被退回",
    "征集志愿": "某批次录取结束后，未完成计划的院校再次征集志愿",
    "位次": "考生高考成绩在全省的排名",
    "一分一段表": "公布每个分数段考生人数的统计表",
    "省控线": "省级招生考试机构划定的各批次最低录取控制分数线",
    "校线": "各高校根据生源情况划定的实际录取分数线",
    "专业线": "高校各专业的最低录取分数",
    "调剂": "考生服从专业调剂，被分配到未录满的专业",
    "大类招生": "按学科大类招生，入学后再进行专业分流",
    "书院制": "高校实行的住宿学院制度，注重通识教育和跨学科培养",
    "双学位": "学生在校期间修读两个专业，毕业获得两个学位证书",
    "辅修": "学生在主修专业之外修读其他专业课程",
    "学分制": "以学分为单位计算学习量的教学管理制度",
    "绩点": "成绩平均绩点，衡量学生学业成绩的指标",
    "保研": "推荐优秀应届本科毕业生免试攻读硕士研究生",
    "考研": "全国硕士研究生统一招生考试",
    "跨考": "跨专业报考研究生",
    "调剂复试": "未被第一志愿录取，调剂到其他院校参加复试",
    "学硕": "学术型硕士研究生，侧重理论研究",
    "专硕": "专业型硕士研究生，侧重实践应用",
    "非全": "非全日制研究生，在职学习",
    "全日制": "全日制在校学习的研究生",
    "定向": "毕业后须到指定单位就业的招生方式",
    "非定向": "毕业后自主择业的招生方式",
    "委培": "委托培养，由用人单位出资委托高校培养",
    "自费": "学生自行承担全部培养费用",
    "公费": "国家或地方财政承担培养费用",
    "奖学金": "奖励优秀学生的资金",
    "助学金": "资助家庭经济困难学生的资金",
    "助学贷款": "向家庭经济困难学生提供的信用贷款",
    "绿色通道": "为家庭经济困难新生提供的先入学后缴费的通道",
    "休学创业": "学生因创业需要申请休学",
    "弹性学制": "允许学生在规定年限内灵活安排学习进度",
    "学分互认": "不同高校之间相互承认学分",
    "交换生": "到国内外合作院校进行短期学习的学生",
    "访学": "到其他高校或研究机构进行学术访问",
    "夏令营": "高校举办的暑期学术活动，常与招生选拔挂钩",
    "冬令营": "高校举办的冬季学术活动",
    "开放日": "高校面向社会开放的参观咨询活动",
    "校园开放日": "高校定期向社会开放校园，展示办学条件",
    "招生简章": "高校发布的招生政策、专业、计划等信息的文件",
    "招生章程": "高校依据国家规定制定的招生规则和承诺",
    "招生计划": "高校各专业拟招收的学生人数",
    "录取通知书": "高校向被录取学生发放的正式通知文件",
    "报到": "新生按录取通知书要求到校办理入学手续",
    "注册": "学生到校后办理学籍登记手续",
    "学籍": "学生在校期间的法律身份记录",
    "档案": "记录学生个人经历、成绩、奖惩等信息的文件",
    "政审": "政治审查，部分院校和专业录取前的必要环节",
    "体检": "入学前的身体健康检查",
    "军训": "新生入学后进行的军事训练",
}


class JargonService:
    """黑话翻译服务类"""

    def __init__(self, db_path: Optional[str] = None, terms_file: Optional[str] = None):
        """
        初始化黑话翻译服务

        Args:
            db_path: SQLite数据库路径，默认使用项目data目录
            terms_file: 术语JSON文件路径，默认使用data/jargon/terms.json
        """
        # 确定项目根目录
        self._project_root = Path(__file__).parent.parent.parent

        # 数据库路径
        if db_path:
            self._db_path = Path(db_path)
        else:
            self._db_path = self._project_root / "data" / "jargon" / "jargon.db"

        # 术语文件路径
        if terms_file:
            self._terms_file = Path(terms_file)
        else:
            self._terms_file = self._project_root / "data" / "jargon" / "terms.json"

        # 确保目录存在
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._terms_file.parent.mkdir(parents=True, exist_ok=True)

        # 内存中的术语映射表
        self._jargon_map: Dict[str, str] = {}
        self._reverse_map: Dict[str, str] = {}  # 通俗->术语反向映射

        # 初始化
        self._load_terms()
        self._init_database()

        logger.info(f"黑话翻译服务初始化完成，共加载 {len(self._jargon_map)} 个术语")

    # ============================================================
    # 内部方法：数据加载与数据库初始化
    # ============================================================

    def _load_terms(self) -> None:
        """从JSON文件加载术语词典，合并默认映射"""
        # 先加载默认映射
        self._jargon_map = dict(DEFAULT_JARGON_MAP)

        # 尝试从JSON文件加载
        try:
            if self._terms_file.exists():
                with open(self._terms_file, "r", encoding="utf-8") as f:
                    file_terms = json.load(f)
                if isinstance(file_terms, dict):
                    self._jargon_map.update(file_terms)
                    logger.info(f"从文件加载了 {len(file_terms)} 个术语")
                elif isinstance(file_terms, list):
                    # 支持列表格式：[{"term": "...", "explanation": "..."}]
                    for item in file_terms:
                        if isinstance(item, dict) and "term" in item and "explanation" in item:
                            self._jargon_map[item["term"]] = item["explanation"]
                    logger.info(f"从文件加载了 {len(file_terms)} 个术语（列表格式）")
        except Exception as e:
            logger.warning(f"加载术语文件失败: {e}，使用默认映射")

        # 构建反向映射
        self._rebuild_reverse_map()

    def _rebuild_reverse_map(self) -> None:
        """重建反向映射表"""
        self._reverse_map = {}
        for term, explanation in self._jargon_map.items():
            # 使用解释的前几个关键词作为反向映射的键
            # 这里简单处理：将解释中的关键词提取出来
            keywords = re.findall(r'[\u4e00-\u9fa5]{2,}', explanation)
            for keyword in keywords[:5]:  # 取前5个关键词
                if keyword not in self._reverse_map:
                    self._reverse_map[keyword] = term

    def _init_database(self) -> None:
        """初始化SQLite数据库，创建术语表和翻译历史表"""
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()

            # 术语表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jargon_terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT UNIQUE NOT NULL,
                    explanation TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    tags TEXT DEFAULT '',
                    source TEXT DEFAULT 'system',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 翻译历史表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS translation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    user_id TEXT DEFAULT '',
                    session_id TEXT DEFAULT '',
                    context TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 术语热度统计表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jargon_popularity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT UNIQUE NOT NULL,
                    query_count INTEGER DEFAULT 0,
                    last_queried_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            conn.close()

            # 同步默认术语到数据库
            self._sync_terms_to_db()

            logger.info("数据库初始化完成")
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")

    def _sync_terms_to_db(self) -> None:
        """将内存中的术语同步到数据库"""
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()

            for term, explanation in self._jargon_map.items():
                cursor.execute("""
                    INSERT OR IGNORE INTO jargon_terms (term, explanation, source)
                    VALUES (?, ?, 'system')
                """, (term, explanation))

            conn.commit()
            conn.close()
            logger.info(f"同步 {len(self._jargon_map)} 个术语到数据库")
        except Exception as e:
            logger.error(f"同步术语到数据库失败: {e}")

    # ============================================================
    # 公共方法：术语查询与翻译
    # ============================================================

    def translate(self, text: str, user_id: str = "", session_id: str = "", context: str = "") -> Dict:
        """
        翻译文本中的黑话术语

        Args:
            text: 待翻译的文本
            user_id: 用户ID（可选）
            session_id: 会话ID（可选）
            context: 上下文信息（可选）

        Returns:
            Dict: {
                "original": 原始文本,
                "translated": 翻译后的文本,
                "matches": [{"term": 术语, "explanation": 解释, "position": 位置}],
                "enhanced": 是否使用了RAG增强
            }
        """
        if not text or not text.strip():
            return {
                "original": text,
                "translated": text,
                "matches": [],
                "enhanced": False
            }

        matches = []
        translated = text
        enhanced = False

        # 1. 精确匹配：查找文本中出现的术语
        sorted_terms = sorted(self._jargon_map.keys(), key=len, reverse=True)
        for term in sorted_terms:
            if term in translated:
                explanation = self._jargon_map[term]
                # 记录匹配位置
                positions = []
                start = 0
                while True:
                    pos = translated.find(term, start)
                    if pos == -1:
                        break
                    positions.append(pos)
                    start = pos + len(term)

                matches.append({
                    "term": term,
                    "explanation": explanation,
                    "positions": positions,
                    "match_type": "exact"
                })

                # 在翻译文本中标记
                translated = translated.replace(term, f"{term}({explanation})")

        # 2. RAG增强翻译：如果精确匹配结果太少，尝试模糊匹配
        if len(matches) < 3:
            rag_matches = self._rag_translate(text)
            if rag_matches:
                enhanced = True
                # 合并结果，去重
                existing_terms = {m["term"] for m in matches}
                for rm in rag_matches:
                    if rm["term"] not in existing_terms:
                        matches.append(rm)
                        existing_terms.add(rm["term"])

        # 3. 记录翻译历史
        if matches:
            self._record_translation(matches, user_id, session_id, context)

        return {
            "original": text,
            "translated": translated,
            "matches": matches,
            "enhanced": enhanced
        }

    def _rag_translate(self, text: str) -> List[Dict]:
        """
        RAG增强翻译：基于关键词匹配 + 简单语义相似度

        Args:
            text: 待翻译的文本

        Returns:
            List[Dict]: 匹配到的术语列表
        """
        matches = []

        # 提取文本中的关键词（2-4个中文字符）
        keywords = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)

        # 对每个关键词进行模糊匹配
        for keyword in keywords:
            # 检查反向映射
            if keyword in self._reverse_map:
                term = self._reverse_map[keyword]
                if term not in {m["term"] for m in matches}:
                    matches.append({
                        "term": term,
                        "explanation": self._jargon_map[term],
                        "positions": [],
                        "match_type": "rag_keyword"
                    })
                continue

            # 检查术语的相似度（包含关系）
            for term, explanation in self._jargon_map.items():
                if keyword in term or term in keyword:
                    if term not in {m["term"] for m in matches}:
                        matches.append({
                            "term": term,
                            "explanation": explanation,
                            "positions": [],
                            "match_type": "rag_similar"
                        })
                    break

        return matches

    def _record_translation(self, matches: List[Dict], user_id: str, session_id: str, context: str) -> None:
        """记录翻译历史并更新热度统计"""
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()

            now = datetime.now().isoformat()

            for match in matches:
                # 记录翻译历史
                cursor.execute("""
                    INSERT INTO translation_history (term, explanation, user_id, session_id, context, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (match["term"], match["explanation"], user_id, session_id, context, now))

                # 更新热度统计
                cursor.execute("""
                    INSERT INTO jargon_popularity (term, query_count, last_queried_at)
                    VALUES (?, 1, ?)
                    ON CONFLICT(term) DO UPDATE SET
                        query_count = query_count + 1,
                        last_queried_at = ?
                """, (match["term"], now, now))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"记录翻译历史失败: {e}")

    # ============================================================
    # 公共方法：术语管理（管理员接口）
    # ============================================================

    def add_term(self, term: str, explanation: str, category: str = "", tags: str = "") -> bool:
        """
        添加新术语

        Args:
            term: 术语
            explanation: 解释
            category: 分类（可选）
            tags: 标签（可选）

        Returns:
            bool: 是否成功
        """
        if not term or not explanation:
            logger.warning("术语和解释不能为空")
            return False

        try:
            # 更新内存
            self._jargon_map[term] = explanation
            self._rebuild_reverse_map()

            # 更新数据库
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO jargon_terms (term, explanation, category, tags, source, updated_at)
                VALUES (?, ?, ?, ?, 'admin', CURRENT_TIMESTAMP)
            """, (term, explanation, category, tags))
            conn.commit()
            conn.close()

            # 同步到JSON文件
            self._save_terms_to_file()

            logger.info(f"添加术语成功: {term}")
            return True
        except Exception as e:
            logger.error(f"添加术语失败: {e}")
            return False

    def update_term(self, term: str, explanation: str, category: str = "", tags: str = "") -> bool:
        """
        更新术语

        Args:
            term: 术语
            explanation: 新的解释
            category: 分类（可选）
            tags: 标签（可选）

        Returns:
            bool: 是否成功
        """
        if term not in self._jargon_map:
            logger.warning(f"术语不存在: {term}")
            return False

        return self.add_term(term, explanation, category, tags)

    def delete_term(self, term: str) -> bool:
        """
        删除术语

        Args:
            term: 术语

        Returns:
            bool: 是否成功
        """
        if term not in self._jargon_map:
            logger.warning(f"术语不存在: {term}")
            return False

        try:
            # 从内存删除
            del self._jargon_map[term]
            self._rebuild_reverse_map()

            # 从数据库删除
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jargon_terms WHERE term = ?", (term,))
            conn.commit()
            conn.close()

            # 同步到JSON文件
            self._save_terms_to_file()

            logger.info(f"删除术语成功: {term}")
            return True
        except Exception as e:
            logger.error(f"删除术语失败: {e}")
            return False

    def get_term(self, term: str) -> Optional[Dict]:
        """
        获取单个术语详情

        Args:
            term: 术语

        Returns:
            Optional[Dict]: 术语详情，不存在返回None
        """
        if term not in self._jargon_map:
            return None

        return {
            "term": term,
            "explanation": self._jargon_map[term],
            "category": "",
            "tags": ""
        }

    def list_terms(self, keyword: str = "", page: int = 1, page_size: int = 20) -> Dict:
        """
        列出术语（支持分页和搜索）

        Args:
            keyword: 搜索关键词（可选）
            page: 页码，从1开始
            page_size: 每页数量

        Returns:
            Dict: {
                "total": 总数,
                "page": 当前页码,
                "page_size": 每页数量,
                "items": [{"term": ..., "explanation": ...}]
            }
        """
        items = []
        if keyword:
            # 搜索匹配
            for term, explanation in self._jargon_map.items():
                if keyword in term or keyword in explanation:
                    items.append({"term": term, "explanation": explanation})
        else:
            items = [{"term": t, "explanation": e} for t, e in self._jargon_map.items()]

        # 排序
        items.sort(key=lambda x: x["term"])

        # 分页
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = items[start:end]

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": page_items
        }

    # ============================================================
    # 公共方法：统计与查询
    # ============================================================

    def get_popular_terms(self, limit: int = 10) -> List[Dict]:
        """
        获取热门术语排行

        Args:
            limit: 返回数量

        Returns:
            List[Dict]: 热门术语列表
        """
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("""
                SELECT term, query_count, last_queried_at
                FROM jargon_popularity
                ORDER BY query_count DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            conn.close()

            return [
                {
                    "term": row[0],
                    "query_count": row[1],
                    "last_queried_at": row[2]
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"获取热门术语失败: {e}")
            return []

    def get_translation_history(self, user_id: str = "", limit: int = 50) -> List[Dict]:
        """
        获取翻译历史

        Args:
            user_id: 用户ID（可选）
            limit: 返回数量

        Returns:
            List[Dict]: 翻译历史列表
        """
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()

            if user_id:
                cursor.execute("""
                    SELECT term, explanation, user_id, session_id, context, created_at
                    FROM translation_history
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (user_id, limit))
            else:
                cursor.execute("""
                    SELECT term, explanation, user_id, session_id, context, created_at
                    FROM translation_history
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            return [
                {
                    "term": row[0],
                    "explanation": row[1],
                    "user_id": row[2],
                    "session_id": row[3],
                    "context": row[4],
                    "created_at": row[5]
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"获取翻译历史失败: {e}")
            return []

    def get_statistics(self) -> Dict:
        """
        获取服务统计信息

        Returns:
            Dict: 统计信息
        """
        stats = {
            "total_terms": len(self._jargon_map),
            "total_queries": 0,
            "popular_terms": []
        }

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()

            # 总查询次数
            cursor.execute("SELECT SUM(query_count) FROM jargon_popularity")
            row = cursor.fetchone()
            if row and row[0]:
                stats["total_queries"] = row[0]

            # 热门术语
            cursor.execute("""
                SELECT term, query_count
                FROM jargon_popularity
                ORDER BY query_count DESC
                LIMIT 10
            """)
            stats["popular_terms"] = [
                {"term": row[0], "query_count": row[1]}
                for row in cursor.fetchall()
            ]

            conn.close()
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")

        return stats

    # ============================================================
    # 内部方法：数据持久化
    # ============================================================

    def _save_terms_to_file(self) -> None:
        """将术语保存到JSON文件"""
        try:
            with open(self._terms_file, "w", encoding="utf-8") as f:
                json.dump(self._jargon_map, f, ensure_ascii=False, indent=2)
            logger.info(f"术语已保存到文件: {self._terms_file}")
        except Exception as e:
            logger.error(f"保存术语到文件失败: {e}")

    def reload_terms(self) -> int:
        """
        重新加载术语（从文件和数据库）

        Returns:
            int: 加载的术语数量
        """
        self._load_terms()
        self._sync_terms_to_db()
        return len(self._jargon_map)

    # ============================================================
    # 公共方法：批量操作
    # ============================================================

    def batch_add_terms(self, terms: List[Dict]) -> Dict:
        """
        批量添加术语

        Args:
            terms: 术语列表，每个元素包含 term 和 explanation

        Returns:
            Dict: {"success": 成功数量, "failed": 失败数量, "errors": 错误信息}
        """
        success = 0
        failed = 0
        errors = []

        for item in terms:
            term = item.get("term", "")
            explanation = item.get("explanation", "")
            category = item.get("category", "")
            tags = item.get("tags", "")

            if self.add_term(term, explanation, category, tags):
                success += 1
            else:
                failed += 1
                errors.append(f"添加术语失败: {term}")

        return {
            "success": success,
            "failed": failed,
            "errors": errors
        }

    def batch_delete_terms(self, terms: List[str]) -> Dict:
        """
        批量删除术语

        Args:
            terms: 术语列表

        Returns:
            Dict: {"success": 成功数量, "failed": 失败数量, "errors": 错误信息}
        """
        success = 0
        failed = 0
        errors = []

        for term in terms:
            if self.delete_term(term):
                success += 1
            else:
                failed += 1
                errors.append(f"删除术语失败: {term}")

        return {
            "success": success,
            "failed": failed,
            "errors": errors
        }


# ============================================================
# 单例模式：全局服务实例
# ============================================================
_jargon_service_instance: Optional[JargonService] = None


def get_jargon_service() -> JargonService:
    """
    获取黑话翻译服务单例

    Returns:
        JargonService: 服务实例
    """
    global _jargon_service_instance
    if _jargon_service_instance is None:
        _jargon_service_instance = JargonService()
    return _jargon_service_instance


# ============================================================
# 便捷函数
# ============================================================

def translate_text(text: str, user_id: str = "", session_id: str = "", context: str = "") -> Dict:
    """
    便捷翻译函数

    Args:
        text: 待翻译文本
        user_id: 用户ID
        session_id: 会话ID
        context: 上下文

    Returns:
        Dict: 翻译结果
    """
    service = get_jargon_service()
    return service.translate(text, user_id, session_id, context)


def add_jargon_term(term: str, explanation: str, category: str = "", tags: str = "") -> bool:
    """
    便捷添加术语函数

    Args:
        term: 术语
        explanation: 解释
        category: 分类
        tags: 标签

    Returns:
        bool: 是否成功
    """
    service = get_jargon_service()
    return service.add_term(term, explanation, category, tags)


def list_jargon_terms(keyword: str = "", page: int = 1, page_size: int = 20) -> Dict:
    """
    便捷列出术语函数

    Args:
        keyword: 搜索关键词
        page: 页码
        page_size: 每页数量

    Returns:
        Dict: 术语列表
    """
    service = get_jargon_service()
    return service.list_terms(keyword, page, page_size)


# ============================================================
# 测试入口
# ============================================================
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # 测试服务
    service = get_jargon_service()

    # 测试翻译
    test_text = "今年小升初政策变化很大，大摇号和民办摇号都要注意，还有指标到校也很重要。"
    result = translate_text(test_text)
    print(f"原始文本: {result['original']}")
    print(f"翻译文本: {result['translated']}")
    print(f"匹配术语: {len(result['matches'])} 个")
    for match in result['matches']:
        print(f"  - {match['term']}: {match['explanation']}")

    # 测试统计
    stats = service.get_statistics()
    print(f"\n统计信息:")
    print(f"  总术语数: {stats['total_terms']}")
    print(f"  总查询次数: {stats['total_queries']}")
    print(f"  热门术语: {[t['term'] for t in stats['popular_terms']]}")
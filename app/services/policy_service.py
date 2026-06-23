#!/usr/bin/env python3
"""
app/services/policy_service.py
政策查询服务层：对接k12-rocket政策WIKI库和RAG知识库接口，实现结构化查询和缓存
"""

import json
import hashlib
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

import httpx
from fastapi import HTTPException

logger = logging.getLogger("k12.policy_service")

# ============================================================
# 缓存配置
# ============================================================
CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "policy_cache"
CACHE_TTL_SECONDS = 3600  # 缓存有效期1小时
CACHE_ENABLED = True

# ============================================================
# 外部API配置（从环境变量读取）
# ============================================================
POLICY_WIKI_BASE_URL = os.getenv("POLICY_WIKI_BASE_URL", "http://localhost:8080/api/v1")
RAG_KNOWLEDGE_BASE_URL = os.getenv("RAG_KNOWLEDGE_BASE_URL", "http://localhost:8081/api/v1")
POLICY_API_KEY = os.getenv("POLICY_API_KEY", "")

# ============================================================
# 本地政策数据文件路径
# ============================================================
POLICY_DATA_FILE = Path(__file__).parent.parent.parent / "data" / "policy" / "policy_data.json"


class PolicyService:
    """
    政策查询服务
    提供结构化政策查询、RAG知识库检索、缓存管理等功能
    """

    def __init__(self):
        """初始化服务，创建缓存目录"""
        if CACHE_ENABLED:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._http_client = None
        self._local_policy_data = None  # 本地政策数据缓存

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建HTTP客户端"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {POLICY_API_KEY}",
                    "Content-Type": "application/json",
                    "User-Agent": "K12-Rocket/2.0"
                }
            )
        return self._http_client

    async def close(self):
        """关闭HTTP客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    # ============================================================
    # 本地政策数据加载
    # ============================================================
    def _load_local_policy_data(self) -> List[Dict[str, Any]]:
        """
        从本地JSON文件加载政策数据
        返回政策条目列表
        """
        if self._local_policy_data is not None:
            return self._local_policy_data

        try:
            if not POLICY_DATA_FILE.exists():
                logger.warning(f"政策数据文件不存在: {POLICY_DATA_FILE}")
                return []

            with open(POLICY_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 支持两种格式：直接是列表，或者是包含items字段的对象
            if isinstance(data, list):
                self._local_policy_data = data
            elif isinstance(data, dict) and "items" in data:
                self._local_policy_data = data["items"]
            else:
                logger.warning(f"政策数据文件格式异常: {POLICY_DATA_FILE}")
                self._local_policy_data = []

            logger.info(f"成功加载本地政策数据，共 {len(self._local_policy_data)} 条")
            return self._local_policy_data

        except json.JSONDecodeError as e:
            logger.error(f"政策数据文件JSON解析失败: {e}")
            return []
        except Exception as e:
            logger.error(f"加载政策数据文件失败: {e}")
            return []

    def _reload_local_policy_data(self):
        """强制重新加载本地政策数据"""
        self._local_policy_data = None
        return self._load_local_policy_data()

    # ============================================================
    # 本地政策查询（支持学段/区域/年份筛选）
    # ============================================================
    def query_local_policies(
        self,
        stage: Optional[str] = None,
        region: Optional[str] = None,
        year: Optional[int] = None,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        查询本地政策数据，支持多维度筛选和分页

        Args:
            stage: 学段筛选（如 "小学", "初中", "高中"）
            region: 区域筛选（如 "锦江区", "武侯区"）
            year: 年份筛选
            keyword: 关键词搜索（匹配标题和内容）
            category: 政策类别（如 "入学政策", "升学政策"）
            page: 页码，从1开始
            page_size: 每页条数

        Returns:
            包含查询结果和分页信息的字典
        """
        try:
            policies = self._load_local_policy_data()
            if not policies:
                return {
                    "total": 0,
                    "page": page,
                    "page_size": page_size,
                    "items": [],
                    "filters": {
                        "stage": stage,
                        "region": region,
                        "year": year,
                        "keyword": keyword,
                        "category": category
                    }
                }

            # 应用筛选条件
            filtered = policies.copy()

            # 学段筛选
            if stage:
                stage = stage.strip()
                filtered = [
                    p for p in filtered
                    if p.get("stage") and stage in p["stage"]
                ]

            # 区域筛选
            if region:
                region = region.strip()
                filtered = [
                    p for p in filtered
                    if p.get("region") and region in p["region"]
                ]

            # 年份筛选
            if year is not None:
                filtered = [
                    p for p in filtered
                    if p.get("year") == year
                ]

            # 关键词搜索（标题和内容）
            if keyword:
                keyword = keyword.strip().lower()
                filtered = [
                    p for p in filtered
                    if (p.get("title") and keyword in p["title"].lower())
                    or (p.get("content") and keyword in p["content"].lower())
                    or (p.get("summary") and keyword in p["summary"].lower())
                ]

            # 政策类别筛选
            if category:
                category = category.strip()
                filtered = [
                    p for p in filtered
                    if p.get("category") and category in p["category"]
                ]

            # 按年份降序排序（如果有年份字段）
            filtered.sort(key=lambda x: x.get("year", 0) or 0, reverse=True)

            # 分页
            total = len(filtered)
            total_pages = max(1, (total + page_size - 1) // page_size)
            page = max(1, min(page, total_pages))
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_items = filtered[start_idx:end_idx]

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "items": page_items,
                "filters": {
                    "stage": stage,
                    "region": region,
                    "year": year,
                    "keyword": keyword,
                    "category": category
                }
            }

        except Exception as e:
            logger.error(f"本地政策查询失败: {e}")
            raise HTTPException(status_code=500, detail=f"政策查询失败: {str(e)}")

    # ============================================================
    # 缓存管理
    # ============================================================
    def _get_cache_key(self, query_params: Dict[str, Any]) -> str:
        """生成缓存键"""
        raw = json.dumps(query_params, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return CACHE_DIR / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """读取缓存"""
        if not CACHE_ENABLED:
            return None

        cache_path = self._get_cache_path(cache_key)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            # 检查缓存是否过期
            cached_time = datetime.fromisoformat(cache_data.get("cached_at", "2000-01-01T00:00:00"))
            if datetime.now() - cached_time > timedelta(seconds=CACHE_TTL_SECONDS):
                logger.debug(f"缓存已过期: {cache_key}")
                cache_path.unlink(missing_ok=True)
                return None

            logger.debug(f"缓存命中: {cache_key}")
            return cache_data.get("data")

        except Exception as e:
            logger.warning(f"读取缓存失败: {e}")
            return None

    def _write_cache(self, cache_key: str, data: Any):
        """写入缓存"""
        if not CACHE_ENABLED:
            return

        try:
            cache_path = self._get_cache_path(cache_key)
            cache_data = {
                "cached_at": datetime.now().isoformat(),
                "data": data
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.debug(f"缓存写入成功: {cache_key}")
        except Exception as e:
            logger.warning(f"写入缓存失败: {e}")

    def clear_cache(self, older_than_seconds: Optional[int] = None):
        """
        清理缓存

        Args:
            older_than_seconds: 清理超过指定秒数的缓存，None表示全部清理
        """
        if not CACHE_ENABLED:
            return

        try:
            count = 0
            now = datetime.now()
            for cache_file in CACHE_DIR.glob("*.json"):
                if older_than_seconds is not None:
                    # 检查文件修改时间
                    mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
                    if now - mtime <= timedelta(seconds=older_than_seconds):
                        continue
                cache_file.unlink()
                count += 1
            logger.info(f"清理缓存完成，共清理 {count} 个文件")
        except Exception as e:
            logger.error(f"清理缓存失败: {e}")

    # ============================================================
    # 外部API查询
    # ============================================================
    async def query_wiki_policies(
        self,
        query: str,
        stage: Optional[str] = None,
        region: Optional[str] = None,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        查询政策WIKI库

        Args:
            query: 查询文本
            stage: 学段筛选
            region: 区域筛选
            top_k: 返回结果数量

        Returns:
            政策条目列表
        """
        try:
            client = await self._get_http_client()
            params = {
                "query": query,
                "top_k": top_k
            }
            if stage:
                params["stage"] = stage
            if region:
                params["region"] = region

            response = await client.get(
                f"{POLICY_WIKI_BASE_URL}/search",
                params=params
            )
            response.raise_for_status()
            result = response.json()

            items = result.get("items", []) if isinstance(result, dict) else result
            logger.info(f"WIKI查询成功: query={query}, 结果数={len(items)}")
            return items

        except httpx.HTTPStatusError as e:
            logger.error(f"WIKI API HTTP错误: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=502, detail=f"政策WIKI服务异常: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"WIKI API请求失败: {e}")
            raise HTTPException(status_code=503, detail="政策WIKI服务不可用")
        except Exception as e:
            logger.error(f"查询政策WIKI失败: {e}")
            raise HTTPException(status_code=500, detail=f"查询政策WIKI失败: {str(e)}")

    async def query_rag_knowledge(
        self,
        question: str,
        context: Optional[str] = None,
        top_k: int = 5
    ) -> Dict[str, Any]:
        """
        查询RAG知识库

        Args:
            question: 用户问题
            context: 上下文信息（可选）
            top_k: 返回结果数量

        Returns:
            RAG查询结果
        """
        try:
            client = await self._get_http_client()
            payload = {
                "question": question,
                "top_k": top_k
            }
            if context:
                payload["context"] = context

            response = await client.post(
                f"{RAG_KNOWLEDGE_BASE_URL}/query",
                json=payload
            )
            response.raise_for_status()
            result = response.json()

            logger.info(f"RAG查询成功: question={question[:50]}...")
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"RAG API HTTP错误: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=502, detail=f"RAG知识库服务异常: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"RAG API请求失败: {e}")
            raise HTTPException(status_code=503, detail="RAG知识库服务不可用")
        except Exception as e:
            logger.error(f"查询RAG知识库失败: {e}")
            raise HTTPException(status_code=500, detail=f"查询RAG知识库失败: {str(e)}")

    # ============================================================
    # 综合查询（本地+外部）
    # ============================================================
    async def comprehensive_query(
        self,
        query: str,
        stage: Optional[str] = None,
        region: Optional[str] = None,
        year: Optional[int] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        综合查询：先查本地数据，再查外部API，合并结果

        Args:
            query: 查询关键词
            stage: 学段筛选
            region: 区域筛选
            year: 年份筛选
            use_cache: 是否使用缓存

        Returns:
            综合查询结果
        """
        try:
            # 生成缓存键
            cache_params = {
                "query": query,
                "stage": stage,
                "region": region,
                "year": year
            }
            cache_key = self._get_cache_key(cache_params)

            # 尝试读取缓存
            if use_cache:
                cached_result = self._read_cache(cache_key)
                if cached_result:
                    return cached_result

            # 1. 查询本地数据
            local_result = self.query_local_policies(
                stage=stage,
                region=region,
                year=year,
                keyword=query
            )

            # 2. 查询外部WIKI
            wiki_items = []
            try:
                wiki_items = await self.query_wiki_policies(
                    query=query,
                    stage=stage,
                    region=region,
                    top_k=10
                )
            except HTTPException:
                logger.warning("WIKI查询失败，仅使用本地数据")

            # 3. 查询RAG知识库
            rag_result = None
            try:
                rag_result = await self.query_rag_knowledge(
                    question=query,
                    context=f"学段: {stage or '不限'}, 区域: {region or '不限'}, 年份: {year or '不限'}"
                )
            except HTTPException:
                logger.warning("RAG查询失败，跳过")

            # 4. 合并结果
            combined_result = {
                "query": query,
                "filters": {
                    "stage": stage,
                    "region": region,
                    "year": year
                },
                "local_policies": local_result,
                "wiki_policies": {
                    "total": len(wiki_items),
                    "items": wiki_items
                },
                "rag_answer": rag_result.get("answer") if rag_result else None,
                "rag_sources": rag_result.get("sources", []) if rag_result else [],
                "timestamp": datetime.now().isoformat()
            }

            # 写入缓存
            if use_cache:
                self._write_cache(cache_key, combined_result)

            return combined_result

        except Exception as e:
            logger.error(f"综合查询失败: {e}")
            raise HTTPException(status_code=500, detail=f"综合查询失败: {str(e)}")

    # ============================================================
    # 政策统计
    # ============================================================
    def get_policy_statistics(self) -> Dict[str, Any]:
        """
        获取政策数据统计信息

        Returns:
            统计数据字典
        """
        try:
            policies = self._load_local_policy_data()
            if not policies:
                return {
                    "total": 0,
                    "by_stage": {},
                    "by_region": {},
                    "by_year": {},
                    "by_category": {}
                }

            # 按学段统计
            by_stage = {}
            for p in policies:
                stage = p.get("stage", "未知")
                by_stage[stage] = by_stage.get(stage, 0) + 1

            # 按区域统计
            by_region = {}
            for p in policies:
                region = p.get("region", "未知")
                by_region[region] = by_region.get(region, 0) + 1

            # 按年份统计
            by_year = {}
            for p in policies:
                year = p.get("year", "未知")
                year_str = str(year) if year else "未知"
                by_year[year_str] = by_year.get(year_str, 0) + 1

            # 按类别统计
            by_category = {}
            for p in policies:
                category = p.get("category", "未知")
                by_category[category] = by_category.get(category, 0) + 1

            return {
                "total": len(policies),
                "by_stage": by_stage,
                "by_region": by_region,
                "by_year": by_year,
                "by_category": by_category,
                "last_updated": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"获取政策统计失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取政策统计失败: {str(e)}")


# ============================================================
# 单例模式
# ============================================================
_policy_service_instance: Optional[PolicyService] = None


def get_policy_service() -> PolicyService:
    """获取PolicyService单例"""
    global _policy_service_instance
    if _policy_service_instance is None:
        _policy_service_instance = PolicyService()
    return _policy_service_instance
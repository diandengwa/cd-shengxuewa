"""
四步裁决框架 v2.0 — 点灯蛙核心
Step1 情况理解 → Step2 灰色地带判断 → Step3 竞争烈度+路径推荐 → Step4 时间线+补救
免费层: Step1+基础8段输出 | 付费层: Step1-4完整输出
付费模式重构 — 按次诊断计费方案
"""

import os
import json
import logging
import re
import httpx
from typing import List, Optional, Dict, Any
from .models import (
    DiagnosisRequest, DiagnosisResult, ScenarioType,
    Step1SituationUnderstanding, Step2GrayZone,
    Step3CompetitionAndPaths, Step4Timeline, PathOption,
    CompetitionLevel, PlanType, FamilyInfo, AdvisorResult,
)
from .loaders import wiki_loader, gt_loader, lottery_loader, knowledge_card_loader
from .router import route_question, has_gray_zone, extract_districts
from app.url_extractor import extract_official_url_from_content
from .credits import check_credits, deduct_credit  # 新增导入：配额检查与扣减

logger = logging.getLogger("k12_rocket")

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "45"))

# 禁止词
PROHIBITED_WORDS = [
    "保证录取", "包录取", "百分百录取", "100%录取",
    "走关系", "有关系", "内部关系",
    "内部指标", "内部渠道", "内部名额",
    "花钱买", "买学位", "买名额",
    "报我名字", "找我有路", "有门路",
    "疏通关系", "找关系入学",
]

# 黑话翻译表
JARGON_TABLE = {
    "大摇号": {
        "plain": "市级统筹的电脑随机录取，成都市教育局统一组织的6所名校摇号",
        "scenario": "小升初",
        "policy_ref": "2026年成都市义务教育招生入学政策",
    },
    "小摇号": {
        "plain": "区级统筹的电脑随机录取，按划片范围内摇号",
        "scenario": "小升初",
        "policy_ref": "各区义务教育招生入学实施细则",
    },
    "两个一致": {
        "plain": "户籍地与居住地一致、户籍与法定监护人一致——划片入学的核心条件",
        "scenario": "幼升小/小升初",
        "policy_ref": "成都市义务教育招生入学政策",
    },
    "DZ": {
        "plain": "定向招生——学校自主选拔，非公开渠道（注意：不鼓励，存在合规风险）",
        "scenario": "小升初",
        "policy_ref": "公民同招政策",
    },
    "QY": {
        "plain": "签约——学校与家长签入学意向协议",
        "scenario": "小升初/中考",
        "policy_ref": "各校自主招生政策",
    },
    "JX": {
        "plain": "均衡教育/就近入学——按居住地划片对口入学",
        "scenario": "幼升小/小升初",
        "policy_ref": "义务教育法",
    },
    "随迁": {
        "plain": "进城务工人员随迁子女——非本市户籍在成都申请入学的家庭",
        "scenario": "幼升小/小升初",
        "policy_ref": "成都市随迁子女入学政策",
    },
    "划片": {
        "plain": "按居住地划定的对口入学区域——你的住址决定你能上哪所公办学校",
        "scenario": "幼升小/小升初",
        "policy_ref": "各区划片范围公告",
    },
    "指标到校": {
        "plain": "省级示范性高中将部分招生名额分配到初中学校——校内竞争而非全区竞争",
        "scenario": "中考",
        "policy_ref": "成都市中考政策",
    },
    "公民同招": {
        "plain": "公办和民办学校同步招生——选择民办摇号即放弃公办划片资格（不可逆）",
        "scenario": "幼升小/小升初",
        "policy_ref": "2026年成都市义务教育招生入学政策",
    },
    "信息采集": {
        "plain": "入学信息网上登记——所有升学的第一步，必须按时完成",
        "scenario": "幼升小/小升初",
        "policy_ref": "成都市义务教育招生入学工作日程",
    },
    "多校划片": {
        "plain": "一个区域对口多所学校，通过摇号决定上哪所——不是你想去哪就去哪",
        "scenario": "小升初",
        "policy_ref": "各区小升初划片方案",
    },
}


def filter_prohibited(text: str) -> str:
    """过滤禁止词"""
    if not text:
        return text
    for word in PROHIBITED_WORDS:
        if word in text:
            text = text.replace(word, "⚠️[已过滤:涉嫌违规表述]")
    return text


def build_wiki_context(candidate_pages: List[str], max_chars: int = 12000) -> str:
    """构建Wiki知识上下文，2026优先"""
    context_parts = []
    total_chars = 0
    sorted_pages = sorted(candidate_pages, key=lambda p: 0 if "2026" in p else (1 if "2025" in p else 2))

    for page_path in sorted_pages:
        info = wiki_loader.get_page_info(page_path)
        content = wiki_loader.get_page_content(page_path)
        if info and content:
            title = info.get("title", page_path)
            source = info.get("source_grade", "")
            year = "2026" if "2026" in page_path else ("2025" if "2025" in page_path else "年份未标注")
            header = f"### {title} (数据年份: {year})\n" if not source else f"### [{source}] {title} (数据年份: {year})\n"
            max_page_chars = max_chars - total_chars - len(header)
            if max_page_chars < 200:
                break
            truncated = content[:max_page_chars]
            context_parts.append(header + truncated)
            total_chars += len(header) + len(truncated)
    return "\n\n".join(context_parts)


async def call_deepseek(messages: List[Dict[str, str]], temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """
    调用DeepSeek API
    """
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY 未配置")
        return "【系统提示】AI服务暂不可用，请稍后再试。"

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        async with httpx.AsyncClient(timeout=DEEPSEEK_TIMEOUT) as client:
            response = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            return content
    except httpx.TimeoutException:
        logger.error("DeepSeek API 调用超时")
        return "【系统提示】AI响应超时，请稍后重试。"
    except httpx.HTTPStatusError as e:
        logger.error(f"DeepSeek API HTTP错误: {e.response.status_code}")
        return f"【系统提示】AI服务暂时异常，请稍后再试。"
    except Exception as e:
        logger.error(f"DeepSeek API 调用异常: {str(e)}")
        return "【系统提示】AI服务异常，请稍后再试。"


async def diagnose(request: DiagnosisRequest, user_id: Optional[str] = None) -> DiagnosisResult:
    """
    四步诊断主入口
    在开始深度诊断前调用credits.check_credits，不足时返回付费引导响应。
    """
    # ============================================================
    # 付费模式重构 — 按次诊断计费
    # 在开始深度诊断前检查用户配额
    # ============================================================
    if user_id:
        # 检查用户是否有足够的诊断次数
        credit_check = await check_credits(user_id)
        if not credit_check["has_credits"]:
            # 配额不足，返回付费引导响应
            logger.info(f"用户 {user_id} 配额不足，返回付费引导")
            return DiagnosisResult(
                scenario=request.scenario,
                question=request.question,
                step1=None,
                step2=None,
                step3=None,
                step4=None,
                is_paid=False,
                pay_guide=credit_check.get("pay_guide", {
                    "title": "诊断次数已用完",
                    "message": "您的免费诊断次数已用完，请购买诊断包继续使用。",
                    "action": "去购买",
                    "url": "/pay/packages",
                }),
                error=None,
            )

    # 原有诊断逻辑
    try:
        # 1. 路由分析
        route_result = route_question(request.question, request.scenario)
        scenario = route_result.get("scenario", request.scenario)
        districts = extract_districts(request.question)

        # 2. 构建上下文
        wiki_context = build_wiki_context(route_result.get("candidate_pages", []))

        # 3. 执行Step1（免费层基础输出）
        step1_result = await execute_step1(request, scenario, districts, wiki_context)

        # 4. 判断是否需要付费深度诊断
        needs_deep = route_result.get("needs_deep_diagnosis", False)

        if needs_deep and user_id:
            # 执行付费深度诊断（Step2-4）
            step2_result = await execute_step2(request, scenario, districts, wiki_context, step1_result)
            step3_result = await execute_step3(request, scenario, districts, wiki_context, step1_result, step2_result)
            step4_result = await execute_step4(request, scenario, districts, wiki_context, step1_result, step2_result, step3_result)

            # 扣减一次诊断次数
            if user_id:
                await deduct_credit(user_id)

            return DiagnosisResult(
                scenario=scenario,
                question=request.question,
                step1=step1_result,
                step2=step2_result,
                step3=step3_result,
                step4=step4_result,
                is_paid=True,
                pay_guide=None,
                error=None,
            )
        else:
            # 免费层：仅返回Step1
            return DiagnosisResult(
                scenario=scenario,
                question=request.question,
                step1=step1_result,
                step2=None,
                step3=None,
                step4=None,
                is_paid=False,
                pay_guide={
                    "title": "查看完整诊断报告",
                    "message": "解锁Step2-4深度分析，获取个性化升学路径与时间规划。",
                    "action": "立即解锁",
                    "url": "/pay/unlock",
                } if needs_deep else None,
                error=None,
            )

    except Exception as e:
        logger.error(f"诊断过程异常: {str(e)}", exc_info=True)
        return DiagnosisResult(
            scenario=request.scenario,
            question=request.question,
            step1=None,
            step2=None,
            step3=None,
            step4=None,
            is_paid=False,
            pay_guide=None,
            error=f"诊断服务暂时异常，请稍后重试。错误: {str(e)}",
        )


async def execute_step1(request: DiagnosisRequest, scenario: str, districts: List[str], wiki_context: str) -> Step1SituationUnderstanding:
    """
    执行Step1：情况理解
    """
    # 构建提示词
    system_prompt = """你是一位资深的成都K12升学规划专家，精通成都市及各区升学政策。
请根据用户的问题，进行情况理解分析，输出结构化的分析结果。"""

    user_prompt = f"""用户问题：{request.question}
升学场景：{scenario}
涉及区域：{', '.join(districts) if districts else '未明确'}

参考知识：
{wiki_context[:8000]}

请分析：
1. 用户的核心诉求是什么？
2. 用户当前处于什么升学阶段？
3. 用户的基本情况（户籍、学籍、房产等）？
4. 关键时间节点有哪些？
5. 需要重点关注的政策要点？"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    content = await call_deepseek(messages)

    # 解析返回内容，构建Step1SituationUnderstanding对象
    return Step1SituationUnderstanding(
        summary=content[:500] if content else "分析暂不可用",
        key_points=[],
        concerns=[],
        raw_output=content,
    )


async def execute_step2(request: DiagnosisRequest, scenario: str, districts: List[str],
                        wiki_context: str, step1: Step1SituationUnderstanding) -> Step2GrayZone:
    """
    执行Step2：灰色地带判断
    """
    system_prompt = """你是一位成都K12升学政策专家，擅长识别政策灰色地带和潜在风险。
请基于用户情况和政策要求，分析可能存在的灰色地带和风险点。"""

    user_prompt = f"""用户问题：{request.question}
升学场景：{scenario}
涉及区域：{', '.join(districts) if districts else '未明确'}

情况理解摘要：
{step1.summary if step1 else '暂无'}

参考知识：
{wiki_context[:6000]}

请分析：
1. 是否存在政策灰色地带？
2. 有哪些潜在风险？
3. 需要特别注意的事项？"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    content = await call_deepseek(messages)

    return Step2GrayZone(
        has_gray_zone=has_gray_zone(request.question),
        description=content[:800] if content else "分析暂不可用",
        risks=[],
        suggestions=[],
        raw_output=content,
    )


async def execute_step3(request: DiagnosisRequest, scenario: str, districts: List[str],
                        wiki_context: str, step1: Step1SituationUnderstanding,
                        step2: Step2GrayZone) -> Step3CompetitionAndPaths:
    """
    执行Step3：竞争烈度+路径推荐
    """
    system_prompt = """你是一位成都K12升学规划专家，擅长分析竞争态势和推荐升学路径。
请基于用户情况和区域数据，提供竞争分析和路径建议。"""

    user_prompt = f"""用户问题：{request.question}
升学场景：{scenario}
涉及区域：{', '.join(districts) if districts else '未明确'}

情况理解摘要：
{step1.summary if step1 else '暂无'}

灰色地带分析：
{step2.description if step2 else '暂无'}

参考知识：
{wiki_context[:6000]}

请分析：
1. 该区域的竞争烈度如何？
2. 有哪些可行的升学路径？
3. 各路径的优缺点和成功率？"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    content = await call_deepseek(messages)

    return Step3CompetitionAndPaths(
        competition_level=CompetitionLevel.MEDIUM,
        analysis=content[:1000] if content else "分析暂不可用",
        paths=[],
        recommendation="",
        raw_output=content,
    )


async def execute_step4(request: DiagnosisRequest, scenario: str, districts: List[str],
                        wiki_context: str, step1: Step1SituationUnderstanding,
                        step2: Step2GrayZone, step3: Step3CompetitionAndPaths) -> Step4Timeline:
    """
    执行Step4：时间线+补救
    """
    system_prompt = """你是一位成都K12升学规划专家，擅长制定升学时间线和补救方案。
请基于用户情况，提供详细的时间规划和补救建议。"""

    user_prompt = f"""用户问题：{request.question}
升学场景：{scenario}
涉及区域：{', '.join(districts) if districts else '未明确'}

情况理解摘要：
{step1.summary if step1 else '暂无'}

灰色地带分析：
{step2.description if step2 else '暂无'}

竞争分析：
{step3.analysis if step3 else '暂无'}

参考知识：
{wiki_context[:6000]}

请提供：
1. 详细的升学时间线（按月/周）
2. 关键节点和截止日期
3. 补救方案和备选计划
4. 紧急程度评估"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    content = await call_deepseek(messages)

    return Step4Timeline(
        timeline=[],
        key_dates=[],
        contingency_plans=[],
        urgency_level="normal",
        raw_output=content,
    )
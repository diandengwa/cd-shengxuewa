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
            page_content = content[:max_page_chars]
            context_parts.append(header + page_content)
            total_chars += len(header) + len(page_content)
    return "\n\n".join(context_parts)


async def call_deepseek(messages: List[Dict[str, str]], system_prompt: str = "", temperature: float = 0.7, max_tokens: int = 4096) -> str:
    """调用DeepSeek API"""
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY 未配置")
        raise ValueError("AI服务未配置，请联系管理员")

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + messages if system_prompt else messages,
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
        logger.error("DeepSeek API 请求超时")
        raise TimeoutError("AI服务响应超时，请稍后重试")
    except httpx.HTTPStatusError as e:
        logger.error(f"DeepSeek API HTTP错误: {e.response.status_code} - {e.response.text}")
        raise RuntimeError(f"AI服务异常 (HTTP {e.response.status_code})")
    except Exception as e:
        logger.error(f"DeepSeek API 调用失败: {str(e)}")
        raise RuntimeError(f"AI服务调用失败: {str(e)}")


async def step1_situation_understanding(question: str, family_info: Optional[FamilyInfo] = None) -> Step1SituationUnderstanding:
    """Step1: 情况理解 — 分析用户问题，提取关键信息"""
    system_prompt = """你是一位资深的成都K12升学顾问，擅长分析家长/学生的升学问题。
请仔细分析用户的升学问题，提取关键信息，并以JSON格式返回分析结果。

返回格式：
{
    "scenario": "幼升小|小升初|中考|高考|转学|其他",
    "grade": "幼儿园|小学|初中|高中|其他",
    "key_points": ["关键点1", "关键点2", ...],
    "missing_info": ["缺失信息1", "缺失信息2", ...],
    "urgency": "紧急|较紧急|一般",
    "summary": "对用户情况的简要总结（50字以内）"
}"""

    user_message = f"用户问题：{question}\n"
    if family_info:
        user_message += f"家庭信息：{json.dumps(family_info.dict(), ensure_ascii=False)}"

    try:
        content = await call_deepseek(
            messages=[{"role": "user", "content": user_message}],
            system_prompt=system_prompt,
            temperature=0.3,
            max_tokens=1024,
        )
        # 尝试解析JSON
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return Step1SituationUnderstanding(**result)
        else:
            logger.warning("Step1 返回非JSON格式，使用默认值")
            return Step1SituationUnderstanding(
                scenario=ScenarioType.OTHER,
                grade="其他",
                key_points=["无法解析用户问题"],
                missing_info=[],
                urgency="一般",
                summary="请提供更详细的升学信息"
            )
    except Exception as e:
        logger.error(f"Step1 处理失败: {str(e)}")
        raise


async def step2_gray_zone(question: str, step1_result: Step1SituationUnderstanding) -> Step2GrayZone:
    """Step2: 灰色地带判断 — 识别政策灰色地带和风险点"""
    system_prompt = """你是一位精通成都K12升学政策的专家，擅长识别政策灰色地带和潜在风险。
基于用户问题和情况理解结果，分析是否存在灰色地带和风险点。

返回JSON格式：
{
    "has_gray_zone": true/false,
    "gray_zone_description": "灰色地带描述（如有）",
    "risk_points": [
        {"risk": "风险描述", "level": "高|中|低", "suggestion": "建议"}
    ],
    "policy_reference": "相关政策依据",
    "overall_assessment": "整体评估结论"
}"""

    user_message = f"用户问题：{question}\n情况分析：{json.dumps(step1_result.dict(), ensure_ascii=False)}"

    try:
        content = await call_deepseek(
            messages=[{"role": "user", "content": user_message}],
            system_prompt=system_prompt,
            temperature=0.4,
            max_tokens=2048,
        )
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return Step2GrayZone(**result)
        else:
            logger.warning("Step2 返回非JSON格式，使用默认值")
            return Step2GrayZone(
                has_gray_zone=False,
                gray_zone_description="",
                risk_points=[],
                policy_reference="",
                overall_assessment="未发现明显灰色地带"
            )
    except Exception as e:
        logger.error(f"Step2 处理失败: {str(e)}")
        raise


async def step3_competition_and_paths(question: str, step1_result: Step1SituationUnderstanding, wiki_context: str = "") -> Step3CompetitionAndPaths:
    """Step3: 竞争烈度+路径推荐 — 分析竞争情况并推荐升学路径"""
    system_prompt = """你是一位资深的成都K12升学规划师，擅长分析竞争态势并推荐最优升学路径。
基于用户情况和政策知识，分析竞争烈度并给出具体路径建议。

返回JSON格式：
{
    "competition_level": "激烈|较激烈|中等|较缓和|缓和",
    "competition_analysis": "竞争态势详细分析",
    "recommended_paths": [
        {
            "name": "路径名称",
            "description": "路径详细描述",
            "difficulty": "高|中|低",
            "success_rate": "成功率预估（百分比）",
            "key_actions": ["关键行动1", "关键行动2"],
            "timeline": "时间节点建议"
        }
    ],
    "alternative_paths": [
        {
            "name": "备选路径名称",
            "description": "备选路径描述",
            "difficulty": "高|中|低",
            "success_rate": "成功率预估"
        }
    ],
    "key_factors": ["关键因素1", "关键因素2"],
    "overall_recommendation": "综合推荐意见"
}"""

    user_message = f"用户问题：{question}\n情况分析：{json.dumps(step1_result.dict(), ensure_ascii=False)}"
    if wiki_context:
        user_message += f"\n政策参考：{wiki_context[:3000]}"

    try:
        content = await call_deepseek(
            messages=[{"role": "user", "content": user_message}],
            system_prompt=system_prompt,
            temperature=0.5,
            max_tokens=4096,
        )
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            # 转换路径列表
            paths = [PathOption(**p) for p in result.get("recommended_paths", [])]
            alt_paths = [PathOption(**p) for p in result.get("alternative_paths", [])]
            return Step3CompetitionAndPaths(
                competition_level=CompetitionLevel(result.get("competition_level", "中等")),
                competition_analysis=result.get("competition_analysis", ""),
                recommended_paths=paths,
                alternative_paths=alt_paths,
                key_factors=result.get("key_factors", []),
                overall_recommendation=result.get("overall_recommendation", "")
            )
        else:
            logger.warning("Step3 返回非JSON格式，使用默认值")
            return Step3CompetitionAndPaths(
                competition_level=CompetitionLevel.MEDIUM,
                competition_analysis="无法分析竞争态势",
                recommended_paths=[],
                alternative_paths=[],
                key_factors=[],
                overall_recommendation="请提供更详细的信息以获得精准建议"
            )
    except Exception as e:
        logger.error(f"Step3 处理失败: {str(e)}")
        raise


async def step4_timeline(question: str, step1_result: Step1SituationUnderstanding, step3_result: Step3CompetitionAndPaths) -> Step4Timeline:
    """Step4: 时间线+补救 — 制定详细时间表和补救方案"""
    system_prompt = """你是一位经验丰富的成都K12升学规划师，擅长制定详细的升学时间表和补救方案。
基于用户情况和推荐路径，制定可执行的时间线和补救措施。

返回JSON格式：
{
    "timeline_events": [
        {
            "date": "日期",
            "event": "事件描述",
            "importance": "高|中|低",
            "action_required": "需要采取的行动",
            "deadline": "截止日期"
        }
    ],
    "remedial_measures": [
        {
            "issue": "问题描述",
            "measure": "补救措施",
            "urgency": "紧急|较紧急|一般",
            "expected_outcome": "预期效果"
        }
    ],
    "critical_milestones": ["关键里程碑1", "关键里程碑2"],
    "contingency_plans": ["备选方案1", "备选方案2"],
    "overall_timeline_summary": "整体时间线总结"
}"""

    user_message = f"用户问题：{question}\n情况分析：{json.dumps(step1_result.dict(), ensure_ascii=False)}\n推荐路径：{json.dumps(step3_result.dict(), ensure_ascii=False)}"

    try:
        content = await call_deepseek(
            messages=[{"role": "user", "content": user_message}],
            system_prompt=system_prompt,
            temperature=0.4,
            max_tokens=4096,
        )
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return Step4Timeline(**result)
        else:
            logger.warning("Step4 返回非JSON格式，使用默认值")
            return Step4Timeline(
                timeline_events=[],
                remedial_measures=[],
                critical_milestones=[],
                contingency_plans=[],
                overall_timeline_summary="无法生成时间线"
            )
    except Exception as e:
        logger.error(f"Step4 处理失败: {str(e)}")
        raise


async def diagnose(request: DiagnosisRequest) -> DiagnosisResult:
    """
    四步诊断主流程
    付费模式重构：在深度诊断前检查credits，消耗1次credits，不足时返回付费引导
    """
    question = request.question
    family_info = request.family_info
    user_id = request.user_id  # 用户ID，用于credits检查

    # 过滤禁止词
    question = filter_prohibited(question)

    # Step1: 情况理解（免费层）
    logger.info(f"开始Step1诊断: {question[:50]}...")
    step1_result = await step1_situation_understanding(question, family_info)

    # 基础8段输出（免费层）
    base_output = f"""📋 **情况理解**
- 场景：{step1_result.scenario.value if hasattr(step1_result.scenario, 'value') else step1_result.scenario}
- 年级：{step1_result.grade}
- 关键点：{'、'.join(step1_result.key_points)}
- 紧急程度：{step1_result.urgency}
- 总结：{step1_result.summary}

💡 **基础建议**
1. 请确保信息采集按时完成
2. 关注官方政策发布渠道
3. 建议进行深度诊断获取完整升学方案"""

    # 检查是否需要深度诊断（付费层）
    if not request.deep_diagnosis:
        # 仅返回免费层结果
        return DiagnosisResult(
            step1=step1_result,
            base_output=base_output,
            is_paid=False,
            message="免费诊断完成，如需深度分析请开启深度诊断"
        )

    # ===== 付费模式重构：深度诊断前检查credits =====
    if user_id:
        # 检查用户credits是否充足
        credits_ok, credits_msg = await check_credits(user_id, required=1)
        if not credits_ok:
            logger.info(f"用户 {user_id} credits不足，返回付费引导")
            return DiagnosisResult(
                step1=step1_result,
                base_output=base_output,
                is_paid=False,
                message=credits_msg,  # 返回付费引导信息
                need_payment=True,     # 标记需要付费
                payment_info={
                    "required_credits": 1,
                    "current_credits": 0,
                    "message": credits_msg
                }
            )
        # credits充足，消耗1次
        deduct_success, deduct_msg = await deduct_credit(user_id, amount=1, description=f"深度诊断: {question[:50]}")
        if not deduct_success:
            logger.error(f"用户 {user_id} credits扣减失败: {deduct_msg}")
            return DiagnosisResult(
                step1=step1_result,
                base_output=base_output,
                is_paid=False,
                message="credits扣减失败，请稍后重试",
                need_payment=False,
                error=deduct_msg
            )
        logger.info(f"用户 {user_id} 消耗1次credits，开始深度诊断")
    else:
        # 未登录用户，提示需要登录
        logger.warning("未登录用户尝试深度诊断")
        return DiagnosisResult(
            step1=step1_result,
            base_output=base_output,
            is_paid=False,
            message="请先登录后再进行深度诊断",
            need_payment=False,
            error="用户未登录"
        )

    # ===== 深度诊断流程（付费层） =====
    try:
        # 构建Wiki上下文
        wiki_context = ""
        try:
            candidate_pages = route_question(question)
            if candidate_pages:
                wiki_context = build_wiki_context(candidate_pages)
        except Exception as e:
            logger.warning(f"构建Wiki上下文失败: {str(e)}")

        # Step2: 灰色地带判断
        logger.info("开始Step2诊断")
        step2_result = await step2_gray_zone(question, step1_result)

        # Step3: 竞争烈度+路径推荐
        logger.info("开始Step3诊断")
        step3_result = await step3_competition_and_paths(question, step1_result, wiki_context)

        # Step4: 时间线+补救
        logger.info("开始Step4诊断")
        step4_result = await step4_timeline(question, step1_result, step3_result)

        # 构建完整输出
        full_output = f"""{base_output}

🔍 **灰色地带分析**
{step2_result.overall_assessment}
{'⚠️ 风险提示：' + '；'.join([r['risk'] for r in step2_result.risk_points]) if step2_result.risk_points else '✅ 未发现明显风险'}

📊 **竞争态势分析**
- 竞争烈度：{step3_result.competition_level.value if hasattr(step3_result.competition_level, 'value') else step3_result.competition_level}
- 分析：{step3_result.competition_analysis}

🎯 **推荐路径**
{chr(10).join([f"- {p.name}（难度：{p.difficulty}，成功率：{p.success_rate}）" for p in step3_result.recommended_paths]) if step3_result.recommended_paths else '暂无推荐路径'}

📅 **时间线规划**
{chr(10).join([f"- {e.date}：{e.event}" for e in step4_result.timeline_events]) if step4_result.timeline_events else '暂无时间线信息'}

🆘 **补救措施**
{chr(10).join([f"- {m['issue']}：{m['measure']}" for m in step4_result.remedial_measures]) if step4_result.remedial_measures else '暂无补救措施'}

💎 **综合建议**
{step3_result.overall_recommendation}"""

        return DiagnosisResult(
            step1=step1_result,
            step2=step2_result,
            step3=step3_result,
            step4=step4_result,
            base_output=base_output,
            full_output=full_output,
            is_paid=True,
            message="深度诊断完成"
        )

    except Exception as e:
        logger.error(f"深度诊断失败: {str(e)}")
        # 如果深度诊断失败，但已经扣除了credits，需要记录日志以便后续处理
        if user_id:
            logger.warning(f"用户 {user_id} 深度诊断失败，credits已消耗，需人工核查")
        return DiagnosisResult(
            step1=step1_result,
            base_output=base_output,
            is_paid=False,
            message=f"深度诊断失败: {str(e)}",
            need_payment=False,
            error=str(e)
        )
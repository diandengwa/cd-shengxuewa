#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OPC 内容生成脚本 v3 - 点灯蛙专用 + 多渠道复用
v3 改进（2026-05-30）：
- 标题强制约束注入选题Prompt和写作Prompt
- 选题加时效过滤：过滤2025年旧政策内容
- 70%小升初硬性约束
- 静态内容检测：标题含"养成计划"/"遛娃"/"亲子"等关键词时拒绝生成
"""

import json
import sys
import os
import time
import random
import re
from pathlib import Path
from datetime import datetime
from typing import Any

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

ROOT = Path(r"/app")
KB_DIR = ROOT / "knowledge-base"
# 草稿目录改到工作区，避免沙箱拦截
DRAFTS_DIR = Path(r"C:\Users\TangShaoWan\WorkBuddy\2026-05-28-08-51-47\opc-drafts")
REVIEWED_DIR = ROOT / "reviewed"
READY_DIR = ROOT / "ready-to-publish"

# DeepSeek API
DEEPSEEK_API_KEY = "sk-f563d0eecff44ee4932b8dbd476e0e6e"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# ============================================================
# 标题质量强制约束（高分标题公式）
# ============================================================
TITLE_REQUIREMENTS = """
### 标题强制要求（不满足则整篇作废）
1. 必须包含数字（如"3个"/"28个"/"70%"/"6月2日"）AND 包含情绪词（焦虑/后悔/卡住/错过/可怕/真相/陷阱/必看）
2. 禁止以"实操指南"/"避坑指南"/"完全解读"/"全面解析"结尾
3. 禁止标题里"小升初"出现超过1次（整篇标题最多1个"小升初"）
4. 标题长度12-18字，要有信息量，不是标题党
5. 标题要像成都家长会说的话，不要像公众号小编写的

参考高分标题：
  ✅ "成都小升初6月2日查对应区域：查完后下一步干什么？很多家长卡在这里......"
  ✅ "成都小升初择校：锦江家长后悔没早知道，区内区外竟差了28个指标名额！"
  ❌ "成都小升初报名实操指南"（无数字、无情绪、以指南结尾）
  ❌ "小升初小升初政策解读小升初"（小升初出现3次）
"""

# 静态内容关键词（命中则拒绝生成，移到正确时间窗口）
STATIC_KEYWORDS = [
    "养成计划", "30天", "习惯养成", "遛娃", "亲子互动",
    "不花钱的", "比手机管用", "暑假", "夏令营", "阅读计划",
]

# ============================================================
# 点灯蛙 - 唯一活跃人格
# ============================================================
PERSONA = {
    "name": "点灯蛙",
    "target": "成都K12家长",
    "account": "成都K12教育",
    "voice": """你是一位成都本地的升学政策分析师，不是教育公众号的小编。
你的读者是成都的K12家长，他们焦虑、信息过载、被各种"专家"忽悠。
你的风格：
- 直接说结论，不要铺垫和客套
- 用成都家长听得懂的话，不要官话套话
- 该骂就骂（政策不合理就直说），但骂完要给解决方案
- 数据说话，不说"据悉""据了解"
- 避免一切"值得关注的是""不得不提""不得不说"等套话
- 文章要有信息密度，每段都有增量信息
- 结尾给明确的行动指引，不要"让我们拭目以待"
- 禁止出现：赋能、抓手、闭环、沉淀、方法论、底层逻辑、认知升级""",
    "focus": "升学政策解读、择校分析、时间节点提醒、信息差揭露",
    "structure_hint": "开篇直接抛结论 → 拆解政策/数据 → 指出信息差 → 给行动清单 → 标注风险",
}

# 多渠道分发配置
CHANNELS = {
    "公众号": {
        "format": "长文",
        "word_count": "800-1500字",
        "filename_prefix": "wechat",
        "prompt_suffix": "全文800-1500字，Markdown格式，适合公众号长文阅读。",
    },
    "小红书": {
        "format": "图文卡片",
        "word_count": "200-350字",
        "filename_prefix": "xiaohongshu",
        "prompt_suffix": """改写成小红书图文风格：
- 标题用【】包裹关键词，带emoji前缀但不超过1个
- 正文控制在200-350字
- 用短句+换行，适合手机竖屏阅读
- 3-5个要点用数字标注
- 结尾加话题标签 #成都升学 #K12 #小升初 等
- 不要照搬原文，要提炼核心信息差""",
    },
    "朋友圈": {
        "format": "短文案",
        "word_count": "50-100字",
        "filename_prefix": "moments",
        "prompt_suffix": """改写成朋友圈短文案：
- 50-100字，1-3句话
- 开头要有信息差冲击感（"很多家长不知道..." "刚出的政策..."）
- 结尾引导行动（"评论区留言" "加群" 等）
- 不要用标题，直接正文
- 可以用1-2个emoji但不能多""",
    },
    "微信群": {
        "format": "群激活文案",
        "word_count": "100-200字",
        "filename_prefix": "group",
        "prompt_suffix": """改写成微信群激活文案：
- 100-200字
- 语气像群里说话，不要像公众号推文
- 要有"大家""群里""我们"等社群感
- 包含一个具体的政策信息差
- 结尾引导互动（"有家长遇到过吗""你们区呢"）
- 适当提及资料包或诊断服务""",
    },
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def today_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def call_deepseek(system_prompt: str, user_prompt: str, max_retries: int = 3, temperature: float = 0.7) -> str | None:
    """调用DeepSeek API"""
    import urllib.request

    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 4000,
    }).encode('utf-8')

    req = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        }
    )

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result['choices'][0]['message']['content']
        except Exception as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 5
                print(f"    API retry in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"    API failed after {max_retries} retries: {e}")
                return None


# ============================================================
# 选题：从知识卡片中组合出高价值选题
# ============================================================
TOPIC_PROMPT = """你是一个内容选题策划。根据以下知识卡片，策划1个有爆款潜力的选题。

## 标题强制要求（不满足则整篇作废）
{title_requirements}

## 规则
- 选题必须来自卡片中的事实，不要编造
- 优先选择有时效性（正在发生/即将发生）的话题
- 优先选择有信息差（多数人不知道/容易误解）的角度
- 避免泛泛而谈，要找一个具体的切口
- 选题角度要比普通公众号更锐利、更直接
- **禁止**生成以"实操指南"/"避坑指南"/"完全解读"/"全面解析"结尾的标题
- **禁止**标题里"小升初"出现超过1次
- **必须**在标题里加入数字（日期/百分比/数量）和情绪词（卡住/后悔/错过/可怕/真相/陷阱/必看）

## 可用知识卡片
{cards_text}

## 输出格式（严格JSON）
```json
{{
  "title": "文章标题（严格按上述要求生成，12-18字，有信息量）",
  "angle": "切入角度（为什么这个选题值得写）",
  "target_reader": "目标读者画像（必须是成都K12家长，优先小升初家长）",
  "key_points": ["要点1", "要点2", "要点3"],
  "urgency": "high/medium/low（时效性）",
  "info_gap": "这个选题揭示的信息差是什么",
  "target_grade": "小升初/幼升小/中考/高考"
}}
```"""

# 静态内容检测
def is_static_content(title: str) -> bool:
    """检测是否为静态内容（应在正确时间窗口发布）"""
    for kw in STATIC_KEYWORDS:
        if kw in title:
            return True
    return False


def select_cards_for_topic(count: int = 8) -> list[dict]:
    """为选题挑选知识卡片（点灯蛙专用权重 + 时效过滤）"""
    all_cards = []
    for cat_dir in KB_DIR.iterdir():
        if not cat_dir.is_dir() or cat_dir.name.startswith('.') or cat_dir.name == 'index.json':
            continue
        for card_file in cat_dir.glob('*.json'):
            try:
                card = json.loads(card_file.read_text(encoding='utf-8'))
                if card.get('title') and card.get('content'):
                    all_cards.append(card)
            except Exception:
                pass

    if not all_cards:
        return []

    # 点灯蛙权重：信息差>痛点>事实>决策框架
    def weight(c):
        w = 1.0
        if c.get('category') == 'gap-analysis': w += 2.0
        if c.get('category') == 'pain-points': w += 1.5
        if c.get('category') == 'fact-claims': w += 1.0
        if c.get('actionable'): w += 1.0

        title = c.get('title', '')
        content = c.get('content', '')

        # 时效性加分：标题含2026/最新/今年等
        if any(kw in title for kw in ['2026', '最新', '今年', '新规', '调整', '变化', '新增']):
            w += 2.0
        # 时效性扣分：内容含2025年且不含2026（旧政策内容）
        if '2025' in title and '2026' not in title and '2025' in content[:200]:
            w -= 3.0
        # 时效性扣分：内容是关于"去年"/"上一年"的
        if any(kw in content[:200] for kw in ['去年同期', '去年此时', '2025年同期']):
            w -= 2.0

        return max(w, 0.1)  # 最低0.1，避免全为0

    # 加权随机选择
    weights = [weight(c) for c in all_cards]
    total = sum(weights)
    probs = [w / total for w in weights]

    selected_indices = set()
    selected = []
    attempts = 0
    while len(selected) < min(count, len(all_cards)) and attempts < count * 3:
        idx = random.choices(range(len(all_cards)), weights=probs, k=1)[0]
        if idx not in selected_indices:
            selected_indices.add(idx)
            selected.append(all_cards[idx])
        attempts += 1

    return selected


def generate_topic(cards: list[dict]) -> dict | None:
    """从知识卡片中生成选题（强制返回target_grade）"""
    cards_text = ""
    for i, card in enumerate(cards, 1):
        cards_text += f"\n### 卡片{i} [{card.get('category', '')}] {card.get('title', '')}\n"
        cards_text += f"来源: {card.get('source_name', '')}\n"
        cards_text += f"内容: {card.get('content', '')}\n"
        if card.get('evidence'):
            cards_text += f"原文: {card.get('evidence', '')}\n"

    prompt = TOPIC_PROMPT.format(
        title_requirements=TITLE_REQUIREMENTS,
        cards_text=cards_text,
    )

    response = call_deepseek("你是选题策划专家，必须严格遵守标题要求，必须返回target_grade字段。", prompt, temperature=0.8)
    if not response:
        return None

    # 解析JSON（支持两种格式）
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    raw_json = None
    if json_match:
        try:
            raw_json = json.loads(json_match.group(1))
        except Exception:
            pass
    if not raw_json:
        try:
            raw_json = json.loads(response.strip())
        except Exception:
            print(f"    ⚠️ 选题JSON解析失败: {response[:100]}")
            return None

    # 验证标题是否合规
    title = raw_json.get('title', '')
    if not title:
        return None
    if is_static_content(title):
        print(f"    ⚠️ 标题疑似静态内容，跳过: {title}")
        return None

    # 强制补全target_grade
    if not raw_json.get('target_grade'):
        title_and_content = title + ' ' + str(raw_json.get('angle', ''))
        if '小升初' in title_and_content or '六年级' in title_and_content or '摇号' in title_and_content or '指标' in title_and_content:
            raw_json['target_grade'] = '小升初'
        elif '幼升小' in title_and_content or '划片' in title_and_content or '入学' in title_and_content:
            raw_json['target_grade'] = '幼升小'
        elif '中考' in title_and_content:
            raw_json['target_grade'] = '中考'
        else:
            raw_json['target_grade'] = '小升初'  # 默认小升初

    return raw_json


# ============================================================
# 生成：公众号长文
# ============================================================
ARTICLE_PROMPT = """你是一个公众号写手。请根据以下选题和素材，写一篇公众号文章。

## 人格设定
{persona_voice}

## 选题
- 标题: {topic_title}
- 角度: {topic_angle}
- 目标读者: {target_reader}
- 关键要点: {key_points}
- 信息差: {info_gap}

## 标题强制要求（不满足则整篇作废）
{title_requirements}

## 可用素材
{materials_text}

## 写作要求

### 绝对禁止
1. 不要用任何"AI味"表达：赋能/抓手/闭环/沉淀/方法论/底层逻辑/认知升级/降维打击/生态/赛道
2. 不要用新闻腔："值得关注的是"/"不得不提"/"业内人士指出"/"据统计"
3. 不要用空洞过渡句："下面我们来详细了解一下"/"让我们一起来看看"
4. 不要在结尾说"让我们拭目以待"/"未来可期"/"值得期待"
5. 不要堆砌标题，正文用自然段落而非全用小标题
6. 不要用emoji做装饰

### 必须做到
1. 开头3句话内给出核心结论
2. 每个段落有信息增量，不是重复前面说过的话
3. 引用的数据/事实要标注来源
4. 给出具体可执行的行动建议
5. 如有风险，明确标注
6. 全文800-1500字，信息密度优先
7. **70%内容约束**：全文70%以上内容围绕小升初，最多30%内容涉及幼升小/中考/高考
8. **标题必须匹配选题标题**：用上面"选题"里的标题，不要另起标题

### 结构建议
{structure_hint}

## 输出
直接输出文章正文，Markdown格式。不要输出任何元数据、注释或说明。"""


def generate_article(topic: dict, cards: list[dict]) -> str | None:
    """根据选题和素材生成公众号长文"""
    # 准备素材文本
    materials = ""
    for i, card in enumerate(cards, 1):
        materials += f"\n### 素材{i} [{card.get('category', '')}] {card.get('title', '')}\n"
        materials += f"来源: {card.get('source_name', '')}\n"
        materials += f"内容: {card.get('content', '')}\n"
        if card.get('evidence'):
            materials += f"原文引用: {card.get('evidence', '')}\n"

    key_points = topic.get('key_points', [])
    if isinstance(key_points, list):
        key_points_str = '、'.join(str(p) for p in key_points)
    else:
        key_points_str = str(key_points)

    prompt = ARTICLE_PROMPT.format(
        persona_voice=PERSONA['voice'],
        topic_title=topic.get('title', ''),
        topic_angle=topic.get('angle', ''),
        target_reader=topic.get('target_reader', PERSONA['target']),
        key_points=key_points_str,
        info_gap=topic.get('info_gap', ''),
        title_requirements=TITLE_REQUIREMENTS,
        materials_text=materials,
        structure_hint=PERSONA['structure_hint'],
    )

    return call_deepseek(PERSONA['voice'], prompt, temperature=0.7)


# ============================================================
# 多渠道复用：从公众号长文改写为其他平台版本
# ============================================================
REPURPOSE_PROMPT = """你是一个内容改编专家。请将以下公众号文章改写成{channel_name}格式。

## 原文
{article_text}

## 改写要求
{channel_prompt}

## 输出
直接输出改写后的内容，不要输出任何说明或注释。"""


def repurpose_for_channel(article: str, channel_name: str) -> str | None:
    """将公众号长文改写为其他平台版本"""
    channel = CHANNELS[channel_name]
    prompt = REPURPOSE_PROMPT.format(
        channel_name=channel_name,
        article_text=article[:3000],  # 截断避免超长
        channel_prompt=channel['prompt_suffix'],
    )
    return call_deepseek(PERSONA['voice'], prompt, temperature=0.7)


# ============================================================
# 去AI味检查
# ============================================================
AI_SMELL_SINGLE = [
    r"赋能", r"抓手", r"闭环", r"沉淀", r"方法论", r"底层逻辑",
    r"认知升级", r"降维打击", r"生态(?!圈)", r"赛道", r"矩阵",
    r"值得关注的是", r"不得不提", r"不得不说",
    r"让我们拭目以待", r"未来可期",
]


def check_ai_smell(text: str) -> list[str]:
    """检测文章中的AI味"""
    found = []
    for pattern in AI_SMELL_SINGLE:
        matches = re.findall(pattern, text)
        if matches:
            found.append(f"'{matches[0]}' 出现{len(matches)}次")
    return found


# ============================================================
# 审稿：严格12分制
# ============================================================
def score_article(text: str, topic_title: str = '') -> tuple[float, list[str]]:
    """严格评分文章质量，满分12分"""
    score = 0.0
    issues = []

    # 0. 标题合规检查（新增）
    if topic_title:
        title_score = 0
        # 含数字
        if re.search(r'\d+', topic_title):
            title_score += 1
        # 含情绪词
        if any(kw in topic_title for kw in ['焦虑', '后悔', '卡住', '错过', '可怕', '真相', '陷阱', '必看', '?', '？']):
            title_score += 1
        # 不以禁词结尾
        if not any(topic_title.endswith(suffix) for suffix in ['实操指南', '避坑指南', '完全解读', '全面解析']):
            title_score += 1
        # 小升初不超过1次
        if topic_title.count('小升初') <= 1:
            title_score += 1
        if title_score < 3:
            issues.append(f"标题合规性不足({title_score}/4)：{topic_title}")

    # 1. 篇幅 (0-2分)
    char_count = len(text)
    if char_count >= 800:
        score += 2.0
    elif char_count >= 500:
        score += 1.0
        issues.append(f"篇幅偏短({char_count}字)，建议800字以上")
    else:
        issues.append(f"篇幅过短({char_count}字)，严重不足")

    # 2. 信息密度 (0-3分)
    data_patterns = [
        r'\d+月\d+日?', r'\d+%+', r'\d+万', r'\d+人',
        r'\d+所', r'\d+个', r'成都\w+区',
    ]
    data_count = sum(len(re.findall(p, text)) for p in data_patterns)
    if data_count >= 5:
        score += 3.0
    elif data_count >= 3:
        score += 2.0
    elif data_count >= 1:
        score += 1.0
    else:
        issues.append("缺乏具体数据支撑，信息密度不足")

    # 3. 行动指引 (0-2分)
    action_patterns = [
        r'(?:需要|务必|一定要?|请?记得|别?忘了|建议|可以|记得)\s*[^\n。]{5,}',
        r'\d+月\d+日?\s*[前后至到]\s*',
    ]
    action_count = sum(len(re.findall(p, text)) for p in action_patterns)
    if action_count >= 3:
        score += 2.0
    elif action_count >= 1:
        score += 1.0
    else:
        issues.append("缺少可执行的行动指引")

    # 4. AI味扣分 (0-2分)
    ai_smells = check_ai_smell(text)
    if not ai_smells:
        score += 2.0
    elif len(ai_smells) <= 2:
        score += 1.0
        issues.append(f"存在AI味表达: {', '.join(ai_smells)}")
    else:
        issues.append(f"AI味严重: {', '.join(ai_smells)}")

    # 5. 开头直给 (0-1分)
    first_3_lines = '\n'.join(text.split('\n')[:5])
    if any(kw in first_3_lines for kw in ['结论', '重点', '核心', '注意', '变了', '调整', '截止', '开始']):
        score += 1.0
    elif len(first_3_lines) > 20:
        score += 0.5
    else:
        issues.append("开头不够直接，3句话内应给核心结论")

    # 6. 风险标注 (0-1分)
    risk_patterns = [r'风险', r'注意', r'可能(?:会?)?(?:不|无法|被|错过)', r'不要?要?只', r'条件是', r'限制']
    if any(re.search(p, text) for p in risk_patterns):
        score += 1.0

    # 7. 来源标注 (0-1分)
    source_patterns = [r'来源[：:]', r'据\w+(?:局|厅|委|部|发布|教育)', r'官方', r'原文']
    if any(re.search(p, text) for p in source_patterns):
        score += 1.0
    else:
        issues.append("缺少信息来源标注")

    score = round(max(0.0, min(score, 12.0)), 1)
    return score, issues


# ============================================================
# 主流程
# ============================================================
def generate_one(max_attempts: int = 2) -> dict | None:
    """生成一篇公众号文章（含多渠道复用）"""
    for attempt in range(max_attempts):
        print(f"\n  [点灯蛙] 尝试 {attempt + 1}/{max_attempts}")

        # 1. 选择知识卡片
        cards = select_cards_for_topic(count=8)
        if not cards:
            print(f"    无可用知识卡片")
            continue

        print(f"    选中{len(cards)}张卡片")

        # 2. 生成选题
        topic = generate_topic(cards)
        if not topic or not topic.get('title'):
            print(f"    选题生成失败")
            continue

        # 检查70%小升初约束
        target_grade = topic.get('target_grade', '')
        if target_grade and '小升初' not in target_grade and attempt < max_attempts - 1:
            print(f"    ⚠️ 选题非小升初为主，重试... (target_grade={target_grade})")
            continue

        print(f"    选题: {topic.get('title', '')}")
        print(f"    角度: {topic.get('angle', '')}")

        # 3. 生成公众号长文
        article = generate_article(topic, cards)
        if not article:
            print(f"    文章生成失败")
            continue

        # 4. 评分
        score, issues = score_article(article, topic.get('title', ''))
        print(f"    评分: {score}/12")
        if issues:
            print(f"    问题: {'; '.join(issues[:3])}")

        if score >= 8.0:
            print(f"    >> 通过")
        elif score >= 6.0 and attempt < max_attempts - 1:
            print(f"    ~ 边缘分数，尝试改进...")
            continue
        else:
            print(f"    xx 不通过")

        return {
            "persona": "点灯蛙",
            "topic": topic,
            "article": article,
            "score": score,
            "issues": issues,
            "cards_used": len(cards),
            "attempt": attempt + 1,
            "char_count": len(article),
        }

    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description='OPC点灯蛙内容生成 v3')
    parser.add_argument('--count', type=int, default=2,
                       help='生成文章数（默认: 2）')
    parser.add_argument('--channels', nargs='+', default=['公众号', '小红书', '朋友圈', '微信群'],
                       choices=list(CHANNELS.keys()),
                       help='分发渠道（默认: 全部4个）')
    parser.add_argument('--dry-run', action='store_true',
                       help='仅选题不生成文章')
    parser.add_argument('--min-score', type=float, default=8.0,
                       help='最低通过分数（默认: 8.0）')
    parser.add_argument('--no-repurpose', action='store_true',
                       help='不生成多渠道版本，仅公众号长文')
    args = parser.parse_args()

    out_dir = DRAFTS_DIR / today_str()
    out_dir.mkdir(parents=True, exist_ok=True)
    channels_dir = out_dir / "channels"
    channels_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for i in range(args.count):
        print(f"\n{'='*50}")
        print(f"第{i+1}篇")
        print(f"{'='*50}")

        if args.dry_run:
            cards = select_cards_for_topic(count=8)
            topic = generate_topic(cards) if cards else None
            if topic:
                title = topic.get('title', '')
                grade = topic.get('target_grade', '(未标注)')
                print(f"  选题: {title}")
                print(f"  角度: {topic.get('angle', '')}")
                print(f"  目标学段: {grade}")
                # 标题合规检查
                ts = 0
                if re.search(r'\d+', title): ts += 1
                if any(kw in title for kw in ['焦虑','后悔','卡住','错过','可怕','真相','陷阱','必看','?','？']): ts += 1
                if not any(title.endswith(s) for s in ['实操指南','避坑指南','完全解读','全面解析']): ts += 1
                if title.count('小升初') <= 1: ts += 1
                print(f"  标题合规: {ts}/4 {'✅' if ts>=3 else '⚠️'}")
                print(f"  是否静态内容: {'⚠️是，建议移时间窗口' if is_static_content(title) else '✅否'}")
            continue

        result = generate_one()
        if not result:
            print(f"  生成失败，跳过")
            continue

        # 保存公众号长文
        idx = len(results) + 1
        safe_title = re.sub(r'[\\/:*?"<>|]', '', result['topic'].get('title', 'untitled'))[:30]
        draft_file = out_dir / f"draft-{idx:02d}-{safe_title}.md"

        meta = {
            "persona": "点灯蛙",
            "topic": result['topic'],
            "score": result['score'],
            "issues": result['issues'],
            "char_count": result['char_count'],
            "cards_used": result['cards_used'],
            "generated_at": now_iso(),
            "status": "passed" if result['score'] >= args.min_score else "needs_revision",
            "channels": {},
        }

        content = result['article']
        content += f"\n\n---\n\n<!-- meta: {json.dumps(meta, ensure_ascii=False)} -->\n"
        draft_file.write_text(content, encoding='utf-8')
        print(f"  已保存: {draft_file.name} (score={result['score']}, {result['char_count']}字)")

        # 多渠道复用
        if not args.no_repurpose and result['score'] >= args.min_score:
            print(f"  生成多渠道版本...")
            for ch_name in args.channels:
                if ch_name == "公众号":
                    continue  # 公众号是原文
                ch_dir = channels_dir / f"{idx:02d}-{safe_title}"
                ch_dir.mkdir(parents=True, exist_ok=True)

                ch_content = repurpose_for_channel(result['article'], ch_name)
                if ch_content:
                    ch_file = ch_dir / f"{CHANNELS[ch_name]['filename_prefix']}.md"
                    ch_file.write_text(ch_content, encoding='utf-8')
                    meta['channels'][ch_name] = {
                        "file": str(ch_file.relative_to(out_dir)).replace("\\", "/"),
                        "char_count": len(ch_content),
                    }
                    print(f"    {ch_name}: {len(ch_content)}字")
                else:
                    print(f"    {ch_name}: 生成失败")
                time.sleep(1)

            # 更新meta
            content_updated = result['article']
            content_updated += f"\n\n---\n\n<!-- meta: {json.dumps(meta, ensure_ascii=False)} -->\n"
            draft_file.write_text(content_updated, encoding='utf-8')

        results.append(result)
        time.sleep(2)

    # 保存状态（非dry-run才写文件）
    if args.dry_run:
        print(f"\n{'='*50}")
        print("dry-run模式，未生成文章，未写入文件。")
        return 0

    status = {
        "date": today_str(),
        "generated_at": now_iso(),
        "persona": "点灯蛙",
        "total_drafts": len(results),
        "passed": sum(1 for r in results if r['score'] >= args.min_score),
        "needs_revision": sum(1 for r in results if r['score'] < args.min_score),
        "channels": args.channels,
        "results_summary": [
            {
                "file": f"draft-{i+1:02d}-*.md",
                "title": r['topic'].get('title', ''),
                "score": r['score'],
                "char_count": r['char_count'],
                "status": "passed" if r['score'] >= args.min_score else "needs_revision",
            }
            for i, r in enumerate(results)
        ],
    }
    (out_dir / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    print(f"\n{'='*50}")
    print(f"生成完成: {len(results)}篇 | 通过: {status['passed']} | 待修改: {status['needs_revision']}")
    if not args.no_repurpose:
        print(f"多渠道: {', '.join(args.channels)}")

    return 0


if __name__ == '__main__':
    sys.exit(main())

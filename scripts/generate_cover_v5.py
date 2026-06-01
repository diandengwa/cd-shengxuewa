#!/usr/bin/env python3
"""
generate_cover_v5.py — Unsplash 真实摄影 + HTML/CSS 杂志排版 + Playwright 截图

策略：
  1. 根据文章主题自动搜索 Unsplash 高质量照片（官方 API 或预置 URL 池）
  2. 下载到本地作为背景图
  3. HTML/CSS 渲染杂志风格封面（标题在上半区）
  4. Playwright 截图输出最终 PNG
  5. 零 AI 乱码风险（HTML 渲染文字，不需要 OCR）

优势 vs V4（混元底图 + PIL 叠字）：
  - 真实摄影质感，不是 AI 生成的假图
  - HTML 渲染文字 = 完美排版，零乱码
  - 不需要混元 token，不需要 OCR 校验
  - 不需要 60s 冷却时间，生成速度快

关键约束：
  - 封面文字只能在图片上半区（微信多图文模式下底部会被系统标题覆盖）
  - 21:9 封面 (2100×900) + 1:1 次条 (1080×1080)

图片来源（按优先级）：
  1. Unsplash 官方 API 搜索（需 Client-ID，Demo 模式 50 次/小时）
  2. 预置 URL 池（按主题分类的 Unsplash CDN 直链，离线可用）
  3. PIL 渐变色背景（最终 fallback）

依赖：
  - Python 3.13+ (标准库 + Pillow for fallback)
  - Node.js + Playwright (在 scripts/cover-v5/ 目录下)

Usage:
  python generate_cover_v5.py --manifest <path> [--cover-only | --sub-only]
  python generate_cover_v5.py --title "标题" --summary "摘要" --output-dir <path>
  python generate_cover_v5.py --manifest <path> --unsplash-key <client_id>
"""

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

# Fix Windows console encoding
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

SCRIPT_DIR = Path(__file__).parent
NODE_EXE = r"C:\Users\TangShaoWan\.workbuddy\binaries\node\versions\22.22.2\node.exe"
# V5 workspace for Node.js dependencies
# Reuse guizang-test's Playwright install if available
_guizang_test = Path(r"D:\opc\guizang-test")
if (_guizang_test / "node_modules" / "playwright").exists():
    V5_WORKSPACE = _guizang_test
else:
    V5_WORKSPACE = SCRIPT_DIR / "cover-v5"
RENDER_SCRIPT = V5_WORKSPACE / "render_v5.cjs"

# ---- Unsplash keyword mapping ----
# 根据文章标题关键词映射到 Unsplash 搜索词
TOPIC_KEYWORD_MAP = {
    "清单": ["planner desk", "notebook pen", "desk organization"],
    "时间轴": ["calendar desk", "timeline planning", "planner journal"],
    "逐日": ["daily planner", "calendar organize", "desk notes"],
    "步骤": ["step process", "organize desk", "planner"],
    "摇号": ["open door light", "gate pathway", "school building"],
    "民办": ["school campus", "building entrance", "pathway garden"],
    "择校": ["crossroads", "pathway choice", "open gate"],
    "片区": ["aerial city", "city neighborhood", "urban aerial"],
    "划片": ["city map", "urban grid", "aerial view"],
    "区域": ["cityscape aerial", "urban planning", "district"],
    "遛娃": ["meadow flowers", "children playground", "kite sky"],
    "六一": ["summer field", "playground fun", "colorful kite"],
    "亲子": ["family nature", "park happy", "outdoor joy"],
    "游玩": ["amusement park", "green park", "outdoor fun"],
    "幼儿园": ["building blocks", "colorful toys", "pastel blocks"],
    "幼升小": ["school supplies", "backpack books", "pencil colors"],
    "中考": ["study desk lamp", "books focus", "library study"],
    "高考": ["study desk", "books stack", "exam focus"],
    "升学": ["school building", "education path", "books knowledge"],
    "报名": ["form document", "registration desk", "paperwork"],
    "录取": ["acceptance letter", "envelope joy", "celebration"],
    "补录": ["second chance", "open door", "pathway light"],
    "学位": ["school campus", "education building", "university"],
}

DEFAULT_KEYWORDS = ["education books", "knowledge library", "study academic"]

# ---- Local Background Pool ----
# 本地预下载的高质量图片，按主题分类
# 文件名格式: {category}_{wide|square}.jpg
# wide = 2100×900 (21:9 封面), square = 1080×1080 (1:1 次条)
BG_POOL_DIR = SCRIPT_DIR / "cover-v5" / "bg-pool"

# 主题 → 本地图片文件名映射（不含 _wide/_square 后缀和 .jpg 扩展名）
# 优先使用主题适配的图片，同一主题有多个图片则随机选一个
BG_THEME_MAP = {
    # 清单/时间轴/桌面 — 日历、文具、规划
    "清单": ["planner_desk", "workspace_organized", "notebook_journal"],
    "时间轴": ["planner_desk", "workspace_organized"],
    "逐日": ["planner_desk", "notebook_journal"],
    "步骤": ["planner_desk", "workspace_organized"],
    # 摇号/择校/民办 — 校园、建筑、通道
    "摇号": ["school_campus", "architecture_building"],
    "民办": ["school_campus", "architecture_building"],
    "择校": ["school_campus", "architecture_building"],
    # 片区/划片/区域 — 城市、航拍、建筑
    "片区": ["city_modern", "architecture_building"],
    "划片": ["city_modern", "architecture_building"],
    "区域": ["city_modern", "architecture_building"],
    # 遛娃/六一/亲子 — 自然、绿地、阳光
    "遛娃": ["nature_green", "forest_trees", "sunrise_golden"],
    "六一": ["nature_green", "sunrise_golden", "forest_trees"],
    "亲子": ["nature_green", "forest_trees"],
    # 幼儿园/幼升小 — 积木、色彩
    "幼儿园": ["classic_composition", "dark_texture"],
    "幼升小": ["planner_desk", "school_campus"],
    # 中高考 — 书桌、学习
    "中考": ["notebook_journal", "planner_desk", "dark_texture"],
    "高考": ["notebook_journal", "planner_desk", "dark_texture"],
    # 升学/报名/录取
    "升学": ["school_campus", "architecture_building"],
    "报名": ["planner_desk", "notebook_journal"],
    "录取": ["sunrise_golden", "coast_ocean"],
    "补录": ["sunrise_golden", "nature_green"],
    "学位": ["school_campus", "architecture_building"],
    # 通用
    "_default": ["workspace_organized", "planner_desk", "school_campus", "coast_ocean"],
}

# Unsplash API settings (still supported as priority 1 if key provided)
UNSPLASH_API_BASE = "https://api.unsplash.com"


def get_unsplash_keywords(title: str) -> list:
    """根据文章标题匹配 Unsplash 搜索关键词，返回候选词组列表。"""
    matched = []
    for cn_keyword, en_keywords in TOPIC_KEYWORD_MAP.items():
        if cn_keyword in title:
            matched.extend(en_keywords)
    if not matched:
        return DEFAULT_KEYWORDS
    seen = set()
    unique = []
    for kw in matched:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:6]


def _select_bg_from_pool(title: str, is_wide: bool = True, used_categories: set = None) -> Path:
    """
    从本地 bg-pool 中按主题匹配背景图。
    is_wide=True 返回 21:9 封面图，False 返回 1:1 次条图。
    used_categories: 避免同一批文章使用相同主题图片。
    """
    used_categories = used_categories or set()
    suffix = "wide" if is_wide else "square"

    # 按标题关键词匹配主题
    for cn_kw, categories in BG_THEME_MAP.items():
        if cn_kw == "_default":
            continue
        if cn_kw in title:
            # 随机选一个未使用的
            available = [c for c in categories if c not in used_categories]
            if not available:
                available = categories  # 都用过了就重新随机
            chosen = random.choice(available)
            img_path = BG_POOL_DIR / f"{chosen}_{suffix}.jpg"
            if img_path.exists() and img_path.stat().st_size > 5000:
                if chosen not in used_categories:
                    used_categories.add(chosen)
                return img_path

    # 默认池
    default_cats = BG_THEME_MAP["_default"]
    available = [c for c in default_cats if c not in used_categories]
    if not available:
        available = default_cats
    chosen = random.choice(available)
    img_path = BG_POOL_DIR / f"{chosen}_{suffix}.jpg"
    if img_path.exists() and img_path.stat().st_size > 5000:
        used_categories.add(chosen)
        return img_path

    # 兜底：随机选一张
    all_wide = list(BG_POOL_DIR.glob(f"*_{suffix}.jpg"))
    if all_wide:
        return random.choice(all_wide)

    return None


def download_from_local_pool(
    title: str, output_path: Path, width: int, height: int, used_categories: set = None
) -> bool:
    """
    从本地 bg-pool 复制图片到输出路径。
    不需要网络，完全离线可用。
    """
    is_wide = width > height  # 21:9 封面 vs 1:1 次条
    src_path = _select_bg_from_pool(title, is_wide, used_categories)

    if src_path is None:
        print(f"    [WARN] No local bg-pool image found")
        return False

    try:
        import shutil
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src_path), str(output_path))
        print(f"    [OK] Local pool: {src_path.name} -> {output_path.name} ({output_path.stat().st_size//1024}KB)")
        return True
    except Exception as e:
        print(f"    [WARN] Local pool copy failed: {e}")
        return False


def download_from_unsplash_api(
    keyword: str, output_path: Path, width: int, height: int, api_key: str
) -> bool:
    """
    使用 Unsplash 官方 API 搜索并下载图片。
    Demo 模式限制 50 次/小时，足够日常使用。
    """
    encoded_kw = urllib.parse.quote(keyword)
    url = (
        f"{UNSPLASH_API_BASE}/search/photos?"
        f"query={encoded_kw}&orientation=landscape&per_page=5&content_filter=high"
    )

    try:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Client-ID {api_key}",
            "Accept-Version": "v1",
            "User-Agent": "OPC-CoverGenerator/5.0",
        })
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode('utf-8'))

        results = data.get("results", [])
        if not results:
            print(f"    [WARN] No results for keyword: {keyword}")
            return False

        # 随机选一张
        photo = random.choice(results[:3])
        raw_url = photo.get("urls", {}).get("raw", "")
        if not raw_url:
            return False

        # 调整尺寸
        dl_url = f"{raw_url}&auto=format&fit=crop&w={width}&h={height}&q=80"

        return _download_image(dl_url, output_path)

    except Exception as e:
        print(f"    [WARN] Unsplash API error: {e}")
        return False



def _download_image(url: str, output_path: Path) -> bool:
    """通用图片下载函数。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OPC-CoverGenerator/5.0"
        })
        resp = urllib.request.urlopen(req, timeout=30)
        content_type = resp.headers.get('Content-Type', '')

        if 'image' not in content_type and not url.endswith('.jpg'):
            print(f"    [WARN] Not an image: {content_type}")
            return False

        data = resp.read()
        if len(data) < 10000:
            print(f"    [WARN] Image too small: {len(data)} bytes")
            return False

        with open(output_path, 'wb') as f:
            f.write(data)
        print(f"    [OK] Downloaded: {output_path.name} ({len(data)//1024}KB)")
        return True
    except Exception as e:
        print(f"    [WARN] Download failed: {e}")
        return False


def download_cover_bg(
    title: str,
    output_path: Path,
    width: int,
    height: int,
    unsplash_key: str = None,
    used_ids: set = None,
) -> bool:
    """
    下载封面背景图，按优先级尝试：
    1. Unsplash 官方 API（如果提供了 key）
    2. 本地 bg-pool（最可靠，完全离线）
    3. PIL 渐变背景（最终 fallback）
    """
    # 优先级 1: Unsplash API
    if unsplash_key:
        keywords = get_unsplash_keywords(title)
        for kw in keywords[:2]:
            if download_from_unsplash_api(kw, output_path, width, height, unsplash_key):
                return True
            time.sleep(0.5)

    # 优先级 2: 本地 bg-pool
    if download_from_local_pool(title, output_path, width, height, used_ids):
        return True

    # 优先级 3: PIL 渐变背景
    print(f"    [FALLBACK] Creating gradient background")
    _create_fallback_bg(output_path, width, height)
    return True


# ---- Short title for 1:1 sub-cover ----
def make_short_title(title: str) -> str:
    """
    从完整标题中提取短标题，适合 1:1 次条图。
    规则：取核心关键词，不超过 8 个字。
    """
    # 提取关键词模式
    patterns = [
        r"(\d+月[^：:,，]*)",       # "6月逐日操作清单"
        r"([^：:,，]{2,6}攻略)",     # "遛娃攻略"
        r"([^：:,，]{2,6}策略)",     # "摇号策略"
        r"([^：:,，]{2,6}清单)",     # "操作清单"
        r"([^：:,，]{2,6}解读)",     # "政策解读"
        r"([^：:,，]{2,6}问答)",     # "8问8答"
        r"([^：:,，]{2,4}片区)",     # "中和片区"
        r"([^：:,，]{2,6}指南)",     # "报名指南"
    ]
    for p in patterns:
        m = re.search(p, title)
        if m:
            short = m.group(1)
            if len(short) <= 8:
                return short

    # 回退：取标题前 6 个字
    if len(title) <= 8:
        return title
    return title[:6] + "..."


def make_cover_hook(title: str, summary: str = "") -> str:
    """
    为 21:9 封面生成短钩子/金句（4-8 字），显示在封面图上半区。
    原则：精炼、点睛、不重复微信系统标题。4-6 字最佳，最多 8 字。
    """
    t = title

    # === 模式1: 最强钩子 — 核心政策关键词（优先） ===
    strong_hooks = [
        (r"(摇号概率)", "摇号概率"),
        (r"(报名策略)", "报名策略"),
        (r"(摇号策略)", "摇号策略"),
        (r"(逐日清单)", "逐日清单"),
        (r"(操作清单)", "操作清单"),
        (r"(多校划片)", "多校划片"),
        (r"(免费遛娃)", "免费遛娃"),
        (r"(遛娃攻略)", "遛娃攻略"),
        (r"(落户时间)", "落户时间"),
        (r"(志愿填报)", "志愿填报"),
        (r"(录取规则)", "录取规则"),
        (r"(报名指南)", "报名指南"),
        (r"(补录流程)", "补录流程"),
    ]
    for pattern, hook_text in strong_hooks:
        if re.search(pattern, t):
            return hook_text

    # === 模式2: 数字+核心词（次优先） ===
    num_hooks = [
        (r"(\d+问\d+答)", None),      # "8问8答"
        (r"(\d+月\d+日)", None),      # "6月1日"
        (r"限报(\d+所)", None),        # "限报1所" → 整个匹配
        (r"(\d+步)", None),            # "3步"
        (r"(\d+天)", None),            # "3天"
    ]
    for pattern, default in num_hooks:
        m = re.search(pattern, t)
        if m:
            return m.group(0)[:8]  # 最多8字

    # === 模式3: 地名/区域（6字以内） ===
    place_hooks = [
        r"([^，、；：！？·—\s]{2,4}片区)",   # "中和片区"
        r"([^，、；：！？·—\s]{2,4}区划)",   # "高新划片"
    ]
    for p in place_hooks:
        m = re.search(p, t)
        if m:
            return m.group(1)[:6]

    # === 回退：取标题核心实词（最多6字） ===
    # 去掉常见虚词和修饰，只保留核心名词/动词
    cleaned = re.sub(r"[：:,，？！\s]", "", t)
    # 尝试匹配 "X攻略/X策略/X清单/X解读/X指南/X问答"
    m = re.search(r"(.{2,4})(攻略|策略|清单|解读|指南|问答)", cleaned)
    if m:
        return (m.group(1) + m.group(2))[:6]

    # 终极回退：前4-6个实字
    return cleaned[:6]


def make_kicker(title: str) -> str:
    """生成 kicker（分类标签），用于封面顶部。"""
    if "小升初" in title:
        return "成都 · 小升初 · 2026"
    elif "幼升小" in title:
        return "成都 · 幼升小 · 2026"
    elif "中考" in title:
        return "成都 · 中考 · 2026"
    elif "高考" in title:
        return "成都 · 高考 · 2026"
    elif "幼儿园" in title:
        return "成都 · 幼儿园 · 2026"
    elif "遛娃" in title or "六一" in title or "亲子" in title:
        return "成都 · 亲子 · 2026"
    elif "片区" in title or "划片" in title:
        return "成都 · 升学 · 2026"
    else:
        return "点灯蛙 · 2026"


def make_subtitle(title: str, summary: str = "") -> str:
    """生成副标题（摘要缩写），一行可显示。"""
    if summary:
        # 取摘要前 20 字
        s = summary.replace("，", " ").replace("。", "")
        if len(s) > 24:
            return s[:24] + "..."
        return s
    return ""


# ---- HTML Template ----

def build_cover_html(
    bg_image_path: str,
    title: str,
    subtitle: str,
    kicker: str,
    date_str: str,
    is_sub_cover: bool = False,
) -> str:
    """
    生成杂志风格封面的 HTML。
    核心设计：标题在上半区，避免微信多图文底部标题覆盖。
    """
    if is_sub_cover:
        return _build_sub_cover_html(bg_image_path, title, kicker, date_str)
    return _build_wide_cover_html(bg_image_path, title, subtitle, kicker, date_str)


def _build_wide_cover_html(bg_image_path: str, title: str, subtitle: str, kicker: str, date_str: str) -> str:
    """21:9 封面 HTML (2100×900)，标题在上半区。"""

    # 自动换行：标题超过 12 字时强制换行
    title_lines = _split_title(title, max_chars=12)

    title_html = ""
    for line in title_lines:
        title_html += f'<div class="title-line">{_escape_html(line)}</div>\n'

    subtitle_html = ""
    if subtitle:
        subtitle_html = f'<div class="subtitle">{_escape_html(subtitle)}</div>'

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
  /* 字体：使用系统本地字体，不加载外部 Google Fonts（避免 Playwright networkidle 超时） */
  /* Windows: 微软雅黑/宋体 | macOS: PingFang/华文宋体 | Linux: Noto CJK */

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{ background: #1a1816; }}

  #cover {{
    width: 2100px;
    height: 900px;
    position: relative;
    overflow: hidden;
    font-family: "Source Han Serif SC", "Songti SC", "SimSun", "Microsoft YaHei", serif;
  }}

  .bg-photo {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 40%;
    opacity: 0.88;
  }}

  /* 顶部渐变遮罩 — 让标题更易读 */
  .top-gradient {{
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 55%;
    background: linear-gradient(
      to bottom,
      rgba(20, 18, 16, 0.72) 0%,
      rgba(20, 18, 16, 0.45) 35%,
      rgba(20, 18, 16, 0.0) 100%
    );
    z-index: 1;
  }}

  /* 标题区域 — 在上半区 */
  .title-block {{
    position: absolute;
    top: 80px;
    left: 100px;
    right: 100px;
    z-index: 2;
  }}

  .kicker {{
    font-family: "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 18px;
    font-weight: 500;
    letter-spacing: 0.22em;
    color: #c8a96e;
    opacity: 0.92;
    margin-bottom: 24px;
    text-transform: uppercase;
  }}

  .title-line {{
    font-size: 88px;
    font-weight: 600;
    letter-spacing: 0.04em;
    line-height: 1.18;
    color: #fefcf9;
    text-shadow: 0 2px 20px rgba(0,0,0,0.5);
  }}

  .subtitle {{
    font-family: "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 26px;
    font-weight: 300;
    letter-spacing: 0.06em;
    color: #d4c8b8;
    margin-top: 22px;
    line-height: 1.5;
    text-shadow: 0 1px 8px rgba(0,0,0,0.4);
  }}

  /* 顶部金色装饰线 */
  .top-rule {{
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 4px;
    background: #c8a96e;
    z-index: 3;
  }}

  /* 底部品牌条 */
  .bottom-strip {{
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 44px;
    background: #1a1816;
    display: flex;
    align-items: center;
    padding: 0 100px;
    gap: 28px;
    z-index: 3;
  }}

  .bottom-strip span {{
    font-family: "Source Han Sans SC", "Microsoft YaHei", sans-serif;
    font-size: 14px;
    font-weight: 400;
    letter-spacing: 0.10em;
    color: #a89f94;
  }}
</style>
</head>
<body>

<section id="cover">
  <div class="top-rule"></div>
  <img class="bg-photo" src="file:///{bg_image_path}" alt="">
  <div class="top-gradient"></div>
  <div class="title-block">
    <div class="kicker">{kicker}</div>
    {title_html}
    {subtitle_html}
  </div>
  <div class="bottom-strip">
    <span>点灯蛙</span>
    <span>·</span>
    <span>小升初专栏</span>
    <span>·</span>
    <span>{date_str}</span>
  </div>
</section>

</body>
</html>'''


def _build_sub_cover_html(bg_image_path: str, title: str, kicker: str, date_str: str) -> str:
    """1:1 次条封面 HTML (1080×1080)，标题在上半区。"""

    short_title = make_short_title(title)
    title_lines = _split_title(short_title, max_chars=6)

    title_html = ""
    for line in title_lines:
        title_html += f'<div class="title-line">{_escape_html(line)}</div>\n'

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
  /* 字体：使用系统本地字体，不加载外部 Google Fonts（避免 Playwright networkidle 超时） */
  /* Windows: 微软雅黑/宋体 | macOS: PingFang/华文宋体 | Linux: Noto CJK */

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{ background: #1a1816; }}

  #cover {{
    width: 1080px;
    height: 1080px;
    position: relative;
    overflow: hidden;
    font-family: "Source Han Serif SC", "Songti SC", "SimSun", "Microsoft YaHei", serif;
  }}

  .bg-photo {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 35%;
    opacity: 0.85;
  }}

  .top-gradient {{
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 50%;
    background: linear-gradient(
      to bottom,
      rgba(20, 18, 16, 0.70) 0%,
      rgba(20, 18, 16, 0.40) 40%,
      rgba(20, 18, 16, 0.0) 100%
    );
    z-index: 1;
  }}

  .title-block {{
    position: absolute;
    top: 60px;
    left: 60px;
    right: 60px;
    z-index: 2;
  }}

  .kicker {{
    font-family: "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 14px;
    font-weight: 500;
    letter-spacing: 0.24em;
    color: #c8a96e;
    opacity: 0.88;
    margin-bottom: 18px;
  }}

  .title-line {{
    font-size: 68px;
    font-weight: 600;
    letter-spacing: 0.05em;
    line-height: 1.20;
    color: #fefcf9;
    text-shadow: 0 2px 16px rgba(0,0,0,0.5);
  }}

  .top-rule {{
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 4px;
    background: #c8a96e;
    z-index: 3;
  }}

  .bottom-strip {{
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 48px;
    background: #1a1816;
    display: flex;
    align-items: center;
    padding: 0 60px;
    gap: 20px;
    z-index: 3;
  }}

  .bottom-strip span {{
    font-family: "Source Han Sans SC", "Microsoft YaHei", sans-serif;
    font-size: 12px;
    font-weight: 400;
    letter-spacing: 0.08em;
    color: #a89f94;
  }}
</style>
</head>
<body>

<section id="cover">
  <div class="top-rule"></div>
  <img class="bg-photo" src="file:///{bg_image_path}" alt="">
  <div class="top-gradient"></div>
  <div class="title-block">
    <div class="kicker">{kicker}</div>
    {title_html}
  </div>
  <div class="bottom-strip">
    <span>点灯蛙</span>
    <span>·</span>
    <span>{date_str}</span>
  </div>
</section>

</body>
</html>'''


def _split_title(title: str, max_chars: int = 12) -> list:
    """
    将标题拆分为多行，每行不超过 max_chars 字。
    核心原则：要么单行，要么两行尽量对称（字数差不超过1）。
    """
    n = len(title)
    if n <= max_chars:
        return [title]

    # 如果总字数 <= max_chars*2，尽量拆成对称的两行
    if n <= max_chars * 2:
        # 找中间断点：优先在 "和/与/的/，" 处断，否则正中分
        mid = n // 2
        break_chars = "和与的及"
        best_pos = -1
        # 在中间 ±2 字范围内找最佳断点
        for offset in range(0, 3):
            for direction in [0, 1, -1]:
                pos = mid + offset * direction
                if 2 <= pos < n - 2:
                    if title[pos] in break_chars or title[pos] in "，、；：！？·— ":
                        best_pos = pos + 1 if title[pos] in break_chars else pos
                        break
            if best_pos > 0:
                break

        if best_pos > 0:
            return [title[:best_pos], title[best_pos:]]
        # 正中分
        return [title[:mid], title[mid:]]

    # 超过两行限制，强制截断
    lines = []
    remaining = title
    while remaining:
        if len(remaining) <= max_chars:
            lines.append(remaining)
            break
        chunk = remaining[:max_chars]
        # 找最后一个可断点
        break_pos = -1
        for i in range(len(chunk) - 1, max(0, len(chunk) - 4), -1):
            if chunk[i] in "，、；：！？·— 和与的及":
                break_pos = i + 1 if chunk[i] in "和与的及" else i
                break
        if break_pos > 0:
            lines.append(remaining[:break_pos])
            remaining = remaining[break_pos:]
        else:
            lines.append(chunk)
            remaining = remaining[max_chars:]
    return lines


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---- Playwright screenshot ----

def ensure_render_env() -> bool:
    """确保 Playwright 渲染环境就绪。"""
    if not V5_WORKSPACE.exists():
        V5_WORKSPACE.mkdir(parents=True, exist_ok=True)

    package_json = V5_WORKSPACE / "package.json"
    if not package_json.exists():
        package_json.write_text(json.dumps({
            "name": "cover-v5-render",
            "version": "1.0.0",
            "dependencies": {
                "playwright": "^1.60.0"
            }
        }, indent=2), encoding='utf-8')

    node_modules = V5_WORKSPACE / "node_modules"
    if not node_modules.exists():
        print("[SETUP] Installing Playwright...")
        # On Windows, npm is a .cmd file — need shell=True or use node directly
        npm_cmd = r"C:\Users\TangShaoWan\.workbuddy\binaries\node\versions\22.22.2\npm.cmd"
        result = subprocess.run(
            [npm_cmd, "install"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=str(V5_WORKSPACE), timeout=180,
            shell=True,
        )
        if result.returncode != 0:
            print(f"[ERROR] npm install failed: {result.stderr[:500]}")
            return False

        # Install Chromium browser
        print("[SETUP] Installing Chromium browser...")
        npx_cmd = r"C:\Users\TangShaoWan\.workbuddy\binaries\node\versions\22.22.2\npx.cmd"
        result = subprocess.run(
            [npx_cmd, "playwright", "install", "chromium"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=str(V5_WORKSPACE), timeout=300,
            shell=True,
        )
        if result.returncode != 0:
            print(f"[WARN] Chromium install: {result.stderr[:200]}")

    # Write render script
    if not RENDER_SCRIPT.exists():
        _write_render_script()

    return True


def _write_render_script():
    """写入 Playwright 截图脚本。"""
    render_code = r'''const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const args = process.argv.slice(2);
  if (args.length < 3) {
    console.error('Usage: render.cjs <htmlPath> <selector> <outputPath>');
    process.exit(1);
  }

  const [htmlPath, selector, outputPath] = args;
  const absoluteHtml = path.resolve(htmlPath);
  const fileUrl = 'file:///' + absoluteHtml.replace(/\\/g, '/');

  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-settings-window']
    });
    const page = await browser.newPage();
    await page.goto(fileUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(500); // Brief pause for CSS/layout

    const element = await page.$(selector);
    if (!element) {
      console.error('Element not found: ' + selector);
      process.exit(1);
    }

    await element.screenshot({ path: outputPath, type: 'png' });
    console.log('OK:' + outputPath);
  } catch (err) {
    console.error('Render error: ' + err.message);
    process.exit(1);
  } finally {
    if (browser) await browser.close();
  }
})();
'''
    RENDER_SCRIPT.write_text(render_code, encoding='utf-8')
    print(f"[SETUP] Render script written: {RENDER_SCRIPT}")


def render_html_to_png(html_path: Path, selector: str, output_path: Path) -> bool:
    """调用 Playwright 戲图 HTML 元素为 PNG。"""
    cmd = [
        NODE_EXE,
        str(RENDER_SCRIPT),
        str(html_path),
        selector,
        str(output_path),
    ]

    env = os.environ.copy()
    env["NODE_PATH"] = str(V5_WORKSPACE / "node_modules")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
            cwd=str(V5_WORKSPACE),
            env=env,
        )

        if result.returncode != 0:
            print(f"    [ERROR] Render failed: {result.stderr[:300]}")
            return False

        if result.stdout.strip().startswith("OK:"):
            print(f"    [OK] Rendered: {output_path.name} ({output_path.stat().st_size // 1024}KB)")
            return True

        print(f"    [WARN] Unexpected output: {result.stdout[:200]}")
        return output_path.exists() and output_path.stat().st_size > 1000

    except subprocess.TimeoutExpired:
        print(f"    [ERROR] Render timeout")
        return False


# ---- Main pipeline ----

def generate_cover_for_article(
    title: str,
    summary: str,
    manifest_dir: Path,
    cover_rel: str,
    sub_cover_rel: str,
    date_str: str,
    unsplash_key: str = None,
    cover_only: bool = False,
    sub_only: bool = False,
    used_photo_ids: set = None,
) -> tuple:
    """
    为单篇文章生成封面和次条图。
    Returns: (cover_ok: bool, sub_ok: bool)
    """
    used_photo_ids = used_photo_ids or set()
    imgs_dir = manifest_dir / "imgs"
    imgs_dir.mkdir(parents=True, exist_ok=True)

    cover_path = manifest_dir / cover_rel if cover_rel else imgs_dir / f"cover_{hash(title) % 10000}.png"
    sub_path = manifest_dir / sub_cover_rel if sub_cover_rel else imgs_dir / f"sub_{hash(title) % 10000}.png"

    tmp_dir = imgs_dir / "_tmp_v5"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    kicker = make_kicker(title)
    hook = make_cover_hook(title)       # 短钩子，4-12字，用于封面图
    subtitle = make_subtitle(title, summary)

    cover_ok = False
    sub_ok = False

    # ---- Cover (21:9) ----
    if not sub_only:
        if cover_path.exists() and cover_path.stat().st_size > 10000:
            print(f"  [SKIP] Cover exists: {cover_path.name}")
            cover_ok = True
        else:
            print(f"  [COVER] Generating 21:9 for: {title[:30]}...")

            bg_cover = tmp_dir / f"bg_cover_{cover_path.stem}.jpg"
            download_cover_bg(title, bg_cover, 2100, 900, unsplash_key, used_photo_ids)

            bg_path_str = str(bg_cover).replace("\\", "/")
            html_content = build_cover_html(
                bg_path_str, hook, "", kicker, date_str,   # hook 代替完整标题，无副标题
                is_sub_cover=False,
            )
            html_path = tmp_dir / f"cover_{cover_path.stem}.html"
            html_path.write_text(html_content, encoding='utf-8')

            cover_ok = render_html_to_png(html_path, "#cover", cover_path)

            if not cover_ok:
                print(f"  [FAIL] Cover render failed")

    # ---- Sub-cover (1:1) ----
    if not cover_only:
        if sub_path.exists() and sub_path.stat().st_size > 10000:
            print(f"  [SKIP] Sub-cover exists: {sub_path.name}")
            sub_ok = True
        else:
            print(f"  [SUB] Generating 1:1 for: {title[:30]}...")

            bg_sub = tmp_dir / f"bg_sub_{sub_path.stem}.jpg"
            download_cover_bg(title, bg_sub, 1080, 1080, unsplash_key, used_photo_ids)

            bg_path_str = str(bg_sub).replace("\\", "/")
            html_content = build_cover_html(
                bg_path_str, title, "", kicker, date_str,
                is_sub_cover=True,
            )
            html_path = tmp_dir / f"sub_{sub_path.stem}.html"
            html_path.write_text(html_content, encoding='utf-8')

            sub_ok = render_html_to_png(html_path, "#cover", sub_path)

            if not sub_ok:
                print(f"  [FAIL] Sub-cover render failed")

    return cover_ok, sub_ok


def _create_fallback_bg(output_path: Path, width: int, height: int):
    """创建纯色渐变背景作为 Unsplash 下载失败的 fallback。"""
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(img)
        # 简单渐变：深蓝 → 深紫
        for y in range(height):
            r = int(25 + 20 * (y / height))
            g = int(30 + 10 * (y / height))
            b = int(55 + 30 * (y / height))
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        img.save(str(output_path), quality=90)
        print(f"    [FALLBACK] Created gradient bg: {output_path.name}")
    except ImportError:
        # PIL 也不可用，创建一个 1x1 图片然后让 HTML 背景色兜底
        output_path.write_bytes(b'\xff\xd8\xff\xe0\x00\x10JFIF')  # 占位
        print(f"    [FALLBACK] PIL not available, minimal placeholder")


def main():
    parser = argparse.ArgumentParser(description="Generate magazine-style covers via Unsplash + HTML + Playwright")
    parser.add_argument("--manifest", help="Path to manifest.json")
    parser.add_argument("--title", help="Article title (single mode)")
    parser.add_argument("--summary", help="Article summary (single mode)")
    parser.add_argument("--output-dir", help="Output directory (single mode)")
    parser.add_argument("--date", help="Date string for cover (e.g., 2026.05.28)")
    parser.add_argument("--unsplash-key", help="Unsplash API Client-ID (optional, uses preset pool if not provided)")
    parser.add_argument("--cover-only", action="store_true", help="Only generate 21:9 cover")
    parser.add_argument("--sub-only", action="store_true", help="Only generate 1:1 sub-cover")
    parser.add_argument("--force", action="store_true", help="Overwrite existing images")
    args = parser.parse_args()

    # Ensure render environment
    if not ensure_render_env():
        print("[ERROR] Failed to setup render environment")
        sys.exit(1)

    date_str = args.date or _today_str()
    unsplash_key = args.unsplash_key

    # Single article mode
    if args.title:
        output_dir = Path(args.output_dir) if args.output_dir else Path(".")
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = _title_to_slug(args.title)
        cover_rel = f"imgs/{slug}_cover.png"
        sub_rel = f"imgs/{slug}_sub.png"
        cover_ok, sub_ok = generate_cover_for_article(
            args.title, args.summary or "", output_dir,
            cover_rel, sub_rel, date_str,
            unsplash_key=unsplash_key,
            cover_only=args.cover_only, sub_only=args.sub_only,
        )
        sys.exit(0 if (cover_ok and sub_ok) else 1)

    # Manifest mode
    if not args.manifest:
        print("Error: --manifest or --title required")
        sys.exit(1)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Error: manifest not found: {manifest_path}")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    articles = manifest.get("articles", [])
    manifest_dir = manifest_path.parent

    total_covers = 0
    total_subs = 0
    ok_covers = 0
    ok_subs = 0

    # Track used photo IDs to avoid repetition across articles
    used_photo_ids = set()

    for article in articles:
        title = article.get("title", "")
        if not title:
            continue

        summary = article.get("summary", "")
        cover_rel = article.get("cover_image", "")
        sub_rel = article.get("sub_cover_image", "")

        # If force, delete existing images first
        if args.force:
            if cover_rel:
                cp = manifest_dir / cover_rel
                if cp.exists():
                    cp.unlink()
            if sub_rel:
                sp = manifest_dir / sub_rel
                if sp.exists():
                    sp.unlink()

        print(f"\n{'='*60}")
        print(f"[ARTICLE] {title}")
        print(f"{'='*60}")

        cover_ok, sub_ok = generate_cover_for_article(
            title, summary, manifest_dir,
            cover_rel, sub_rel, date_str,
            unsplash_key=unsplash_key,
            cover_only=args.cover_only, sub_only=args.sub_only,
            used_photo_ids=used_photo_ids,
        )

        if not args.sub_only:
            total_covers += 1
            if cover_ok:
                ok_covers += 1
        if not args.cover_only:
            total_subs += 1
            if sub_ok:
                ok_subs += 1

    # Cleanup temp files
    tmp_dir = manifest_dir / "imgs" / "_tmp_v5"
    if tmp_dir.exists():
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n[RESULT] Covers: {ok_covers}/{total_covers} | Sub-covers: {ok_subs}/{total_subs}")

    # Update manifest metadata
    manifest["cover_generated_by"] = "generate_cover_v5.py"
    manifest["cover_generation_summary"] = (
        f"{ok_covers}/{total_covers} covers + {ok_subs}/{total_subs} sub-covers "
        f"via V5 method (Unsplash photo + HTML/CSS + Playwright screenshot)"
    )
    manifest.pop("ocr_results", None)  # V5 doesn't need OCR

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    sys.exit(0 if (ok_covers == total_covers and ok_subs == total_subs) else 1)


def _today_str() -> str:
    """返回今天的日期字符串，格式 2026.05.28。"""
    from datetime import date
    d = date.today()
    return f"{d.year}.{d.month:02d}.{d.day:02d}"


def _title_to_slug(title: str) -> str:
    """将标题转为 slug（用于文件名）。"""
    # 取前 10 个字符，去除特殊字符
    slug = re.sub(r"[^\w\u4e00-\u9fff-]", "", title[:15])
    return slug or "cover"


if __name__ == "__main__":
    main()

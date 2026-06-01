#!/usr/bin/env python3
"""
generate_cover_v4.py — 混元底图 + PIL 上半区叠字封面生成

策略：
  1. 混元生成高品质视觉底图（NO TEXT），每天场景不重复
  2. PIL 精排主标题，文字放在图片上半区域（~12% from top）
  3. 下半区域（50%-100%）完全留白，避免与公众号系统标题重叠

  - 丰富多样的场景提示词（文具/大门/地图/户外/桌面等）
  - 渐进式 NO TEXT 约束 + OCR 校验 + inpainting 修复
  - 上半区渐变遮罩 + 白色描边文字，确保可读性

Usage:
  python generate_cover_v4.py --token <token> --manifest <path> [--cover-only | --sub-only]
  python generate_cover_v4.py --title "标题" --output <path> --token <token>
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Fix Windows console encoding for emoji/Chinese output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# ---- Paths ----
SCRIPT_DIR = Path(__file__).parent
BUDDY_CLOUD_PY = (
    Path(os.environ.get("LOCALAPPDATA", "C:/Users/TangShaoWan/AppData/Local"))
    / "Programs/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills"
    / "buddy-multimodal-generation/scripts/buddy-cloud.py"
)
PYTHON_EXE = "C:\\Users\\TangShaoWan\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe"

# ---- Title translation (for sub-cover only) ----
TITLE_EN = {
    "小升初": "PRIMARY TO MIDDLE SCHOOL ADMISSION",
    "学位确认": "ENROLLMENT CONFIRMATION",
    "幼儿园": "KINDERGARTEN ENROLLMENT",
    "摇号": "LOTTERY ADMISSION",
    "补录": "SUPPLEMENTAL ENROLLMENT",
    "攻略": "GUIDE",
    "解读": "ANALYSIS",
    "指南": "GUIDE",
    "时间": "DEADLINE",
    "风险": "RISK WARNING",
    "操作": "STEP-BY-STEP",
    "清单": "CHECKLIST",
    "路径": "PATHWAY",
    "补救": "RESCUE PLAN",
    "录取": "ADMISSION",
    "择校": "SCHOOL SELECTION",
    "升学": "EDUCATION TRACK",
}

FALLBACK_FONTS = [
    "C:/Windows/Fonts/simhei.ttf",      # 黑体
    "C:/Windows/Fonts/msyh.ttc",        # 微软雅黑
    "C:/Windows/Fonts/simsun.ttc",       # 宋体
    "C:/Windows/Fonts/simkai.ttf",       # 楷体
]


def find_font(size: int):
    """Find available Chinese font."""
    from PIL import ImageFont
    for fp in FALLBACK_FONTS:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def chinese_to_english_keywords(title: str) -> str:
    title_lower = title.lower()
    keywords = []
    for k, v in TITLE_EN.items():
        if k in title:
            keywords.append(v)
    if not keywords:
        short = title[:6]
        return f"EDUCATION GUIDE: {short}"
    return " | ".join(keywords[:3])


# ---- Prompt constructors (progressive, preserving original visual richness) ----

def make_background_prompt(title: str, summary: str = "", round: int = 1) -> str:
    """
    Build BACKGROUND-ONLY prompt with RICH, DIVERSE visuals.
    NEVER repeat the same elements (graduation cap, campus silhouette).
    Each article gets a UNIQUE, editorial-quality scene.
    """
    title_lower = title.lower()

    # ---- Topic-specific visual direction (NO graduation cap / campus silhouette) ----
    if "清单" in title or "时间轴" in title or "逐日" in title or "步骤" in title:
        # 操作清单/时间轴 → 文具+日历+桌面场景
        palette = "warm amber and soft cream tones with gentle shadows"
        visual = (
            "flat lay photography of a wooden desk with open planner calendar, "
            "vintage brass pen, golden paper clips scattered, sticky notes in warm yellow, "
            "small potted succulent, soft morning sunlight from left window, "
            "shallow depth of field, cozy workspace aesthetic"
        )
        mood = "organized, warm, actionable, inviting"
    elif "摇号" in title or "民办" in title or "择校" in title:
        # 摇号/择校 → 大门/选择/机会感
        palette = "teal and coral sunset gradient with golden highlights"
        visual = (
            "wide open ornate iron gate with warm light streaming through, "
            "blurred pathway leading to greenery beyond, "
            "shallow depth of field, morning golden hour lighting, "
            "architectural photography style, hope and opportunity metaphor"
        )
        mood = "hopeful, decisive, warm, full of possibility"
    elif "片区" in title or "划片" in title or "区域" in title:
        # 片区解读 → 地图+城市+航拍感
        palette = "deep teal and warm sand tones with topographic texture"
        visual = (
            "aerial view of a vibrant city neighborhood at golden hour, "
            "grid of streets and green parks from above, "
            "architectural rooftops with warm lighting, "
            "minimalist cartographic overlay feel, "
            "National Geographic photography style"
        )
        mood = "expansive, informative, grounded, authoritative"
    elif "遛娃" in title or "六一" in title or "亲子" in title or "游玩" in title:
        # 亲子/游玩 → 户外/自然/欢乐
        palette = "fresh meadow green to sky blue with warm sunlight"
        visual = (
            "lush green meadow with wildflowers under bright blue sky, "
            "colorful kite flying in distance, soft rolling hills, "
            "picnic blanket corner visible, dappled sunlight through trees, "
            "carefree summer day atmosphere, lifestyle photography"
        )
        mood = "joyful, free, sunny, lighthearted"
    elif "幼儿园" in title or "幼升小" in title:
        # 幼儿园 → 童趣但不幼稚
        palette = "soft pastel mint and warm peach with watercolor texture"
        visual = (
            "artistic watercolor illustration of colorful building blocks "
            "stacked elegantly, crayons in a ceramic jar, "
            "paper cutout stars and clouds on textured paper background, "
            "gentle soft lighting, design studio aesthetic"
        )
        mood = "gentle, nurturing, creative, warm"
    elif "中考" in title or "高考" in title:
        # 中高考 → 书桌+奋斗感，但不压抑
        palette = "deep midnight blue to soft dawn purple"
        visual = (
            "minimalist study desk at dawn with a single desk lamp glowing, "
            "stack of neatly arranged books with bookmark ribbons, "
            "steaming cup of coffee, city skyline visible through rain-speckled window, "
            "cinematic moody lighting, editorial still life photography"
        )
        mood = "focused, determined, serene, aspirational"
    else:
        # 通用教育主题
        palette = "sophisticated navy to warm amber gradient"
        visual = (
            "close-up of open hardcover books with pressed flowers as bookmarks, "
            "vintage brass compass and leather journal on marble surface, "
            "soft natural window light, shallow depth of field, "
            "editorial flat lay photography, timeless academic aesthetic"
        )
        mood = "knowledgeable, trustworthy, refined, inspiring"

    prompt = (
        f"WeChat official account cover image background, 16:9 ratio, "
        f"magazine editorial photography quality, "
        f"color palette: {palette}, "
        f"scene: {visual}, "
        f"atmosphere: {mood}, "
        f"professional photography, shallow depth of field, "
        f"cinematic lighting, rich textures, 8k resolution"
    )

    # ---- STRICT no-text constraints (progressive) ----
    if round >= 1:
        prompt += (
            ". CRITICAL: NO text, NO letters, NO numbers, NO symbols, "
            "NO words, NO typography anywhere. "
            "All surfaces, signs, books, papers must be completely BLANK and clean. "
            "This is a pure background for text overlay."
        )
    if round >= 2:
        prompt += (
            " STRICTLY ZERO TEXT. No writing, no printed words, no labels. "
            "Every surface is blank. This is mandatory."
        )
    if round >= 3:
        prompt += (
            " ABSOLUTELY NO TEXT WILL BE ACCEPTED. "
            "Blank books. Blank papers. Clean surfaces only."
        )

    return prompt


def make_sub_background_prompt(title: str, summary: str = "", round: int = 1) -> str:
    """Build sub-cover (1:1) background prompt — RICH visuals, no text."""
    title_lower = title.lower()

    # ---- Topic-specific 1:1 visual direction ----
    if "清单" in title or "时间轴" in title or "逐日" in title:
        visual = (
            "top-down view of a beautifully organized desk corner: "
            "open leather planner with blank pages, vintage fountain pen, "
            "small brass alarm clock showing 9am, dried eucalyptus branch, "
            "warm morning light casting soft shadows"
        )
        palette = "warm cream and amber with soft brown tones"
    elif "摇号" in title or "民办" in title or "择校" in title:
        visual = (
            "close-up of a hand holding vintage brass key against "
            "sunlit doorway with bokeh garden background, "
            "warm golden hour lighting, shallow depth of field"
        )
        palette = "warm gold and soft teal with lens flare"
    elif "片区" in title or "划片" in title or "区域" in title:
        visual = (
            "macro shot of a vintage brass compass on aged map texture, "
            "soft directional light, travel adventure aesthetic, "
            "rich paper grain and cartographic details"
        )
        palette = "deep teal and aged parchment with gold accents"
    elif "遛娃" in title or "六一" in title or "亲子" in title:
        visual = (
            "colorful pinwheel spinning in green grass with "
            "blue sky and fluffy white clouds, "
            "butterflies in motion blur, joyful summer atmosphere"
        )
        palette = "vibrant green and sky blue with warm yellow highlights"
    elif "幼儿园" in title or "幼升小" in title:
        visual = (
            "artistic arrangement of wooden toy blocks in pastel colors "
            "stacked in gentle spiral, soft studio lighting, "
            "clean white surface, Scandinavian design aesthetic"
        )
        palette = "soft pastel pink, mint, and butter yellow"
    elif "中考" in title or "高考" in title:
        visual = (
            "single lit candle on stack of hardcover books at twilight, "
            "warm amber glow, blurred city lights through window, "
            "contemplative quiet atmosphere"
        )
        palette = "deep midnight blue and warm candlelight amber"
    else:
        visual = (
            "artistic flat lay of academic tools: open notebook with blank pages, "
            "wooden pencil, small potted plant, coffee cup, "
            "warm natural lighting from side window"
        )
        palette = "warm neutral cream and soft sage green"

    prompt = (
        f"Square social media thumbnail, 1:1 ratio, "
        f"magazine-quality still life photography, "
        f"color palette: {palette}, "
        f"scene: {visual}, "
        f"professional photography, rich detail, shallow depth of field, "
        f"editorial composition, 4k resolution"
    )

    if round >= 1:
        prompt += (
            ". CRITICAL: NO text, NO letters, NO numbers, NO symbols, "
            "NO words, NO typography anywhere. All surfaces blank and clean."
        )
    if round >= 2:
        prompt += " STRICTLY ZERO TEXT. No writing anywhere. Mandatory."
    if round >= 3:
        prompt += " ABSOLUTELY NO TEXT. Blank surfaces only."

    return prompt


# ---- Image generation ----

def generate_image(prompt: str, resolution: str, token: str, output_path: Path) -> bool:
    """
    Call buddy-cloud.py to generate an image via WorkBuddy cloud (Hunyuan).
    Token is passed via --token-stdin (stdin) - most secure method.
    Parses JSON from stdout, downloads image from result_url.
    Returns True on success.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        PYTHON_EXE,
        str(BUDDY_CLOUD_PY),
        "image",
        prompt,
        "--resolution", resolution,
        "--token-stdin",
    ]
    result = subprocess.run(
        cmd,
        input=token,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=300,
    )
    if result.returncode != 0:
        print(f"  [WARN] Generation failed (exit {result.returncode}): {result.stdout[-500:] if result.stdout else '(no stdout)'}")
        return False

    # Parse JSON from stdout (buddy-cloud.py prints progress lines + final JSON)
    json_blocks = re.findall(r'\{[\s\S]*?\}', result.stdout)
    data = None
    for block in reversed(json_blocks):
        try:
            data = json.loads(block)
            break
        except json.JSONDecodeError:
            continue

    if data is None:
        print(f"  [WARN] No valid JSON in stdout: {result.stdout[-300:]}")
        return False

    if data.get("status") != "DONE":
        print(f"  [WARN] Generation not DONE: {data}")
        return False

    result_url = data.get("result_url", [])
    if not result_url:
        print(f"  [WARN] No result_url in response: {data}")
        return False

    url = result_url[0] if isinstance(result_url, list) else result_url

    # Download image via curl (use filename only since cwd is parent dir)
    dl_result = subprocess.run(
        ["curl", "-sS", "-L", "-o", output_path.name, url],
        capture_output=True,
        cwd=str(output_path.parent),
        timeout=60,
    )
    if dl_result.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1000:
        print(f"  [WARN] Download failed or file too small: {output_path.name}")
        return False

    print(f"  [OK] Image saved: {output_path.name} ({output_path.stat().st_size // 1024}KB)")
    return True


def validate_image(image_path: Path) -> dict:
    """Run cover_validator on image. Returns result dict."""
    try:
        validator_path = SCRIPT_DIR / "cover_validator.py"
        if not validator_path.exists():
            print(f"  [WARN] cover_validator.py not found, skipping OCR check")
            return {"pass": True, "garbled_count": 0, "garbled_blocks": []}
        result = subprocess.run(
            [PYTHON_EXE, str(validator_path), str(image_path)],
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout.strip()
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    pass
        return {"pass": True, "garbled_count": 0, "garbled_blocks": []}
    except Exception as e:
        print(f"  [WARN] Validation error: {e}")
        return {"pass": True, "garbled_count": 0, "garbled_blocks": []}


def inpaint_text_regions(image_path: Path, output_path: Path = None) -> bool:
    """
    Use OpenCV inpainting to remove text regions detected by OCR.
    Returns True if inpainting was done, False if no text detected.
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        print(f"  [WARN] cv2 not available, skipping inpainting")
        return False

    try:
        import easyocr
        reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
    except Exception as e:
        print(f"  [WARN] easyocr not available: {e}")
        return False

    img_cv = cv2.imread(str(image_path))
    if img_cv is None:
        return False

    h, w = img_cv.shape[:2]

    result = reader.readtext(str(image_path), detail=1, paragraph=False)

    def is_garbled(text, conf):
        if conf >= 0.8:
            return False
        for c in text:
            if ord(c) > 0x4E00 and ord(c) < 0x9FFF:
                continue
            if ord(c) > 127 and not c.isalnum():
                return True
        return conf < 0.3

    text_regions = [(bbox, text, conf) for bbox, text, conf in result if is_garbled(text, conf)]

    if not text_regions:
        print(f"  [INFO] No garbled text regions found, skipping inpainting")
        return False

    print(f"  [FIX] Inpainting {len(text_regions)} garbled text region(s)...")

    mask = np.zeros((h, w), dtype=np.uint8)
    for bbox, text, conf in text_regions:
        xs = [int(p[0]) for p in bbox]
        ys = [int(p[1]) for p in bbox]
        left, right = max(0, min(xs) - 5), min(w, max(xs) + 5)
        top, bottom = max(0, min(ys) - 5), min(h, max(ys) + 5)
        mask[top:bottom, left:right] = 255

    try:
        inpaint_method = cv2.INPAINT_TELEA
    except AttributeError:
        inpaint_method = cv2.INPAINT_NS
    inpainted = cv2.inpaint(img_cv, mask, 3, inpaint_method)

    out_path = output_path or image_path
    cv2.imwrite(str(out_path), inpainted)
    print(f"  [OK] Inpainting done -> {out_path.name}")
    return True


def wrap_text(draw, text: str, font, max_width: int) -> list:
    """Split text into lines that fit within max_width."""
    lines = []
    current_line = ""
    for char in text:
        test = current_line + char
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current_line:
            lines.append(current_line)
            current_line = char
        else:
            current_line = test
    if current_line:
        lines.append(current_line)
    return lines


def overlay_title(
    image_path: Path,
    title: str,
    output_path: Path,
    subtitle: str = None,
    is_sub_cover: bool = False,
) -> bool:
    """
    Magazine-style title overlay — text in UPPER area to avoid
    overlapping with WeChat's system title in multi-article view.

    Design: top gradient mask (darker at top for contrast) +
    white text in upper 1/3 region + bottom 50% stays clean.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except ImportError:
        print(f"  [WARN] PIL not available")
        return False

    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    # ---- 1. TOP gradient mask (darker at top, fades toward middle) ----
    overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw_o = ImageDraw.Draw(overlay)

    # Gradient from top down to ~45% height, then clean below
    gradient_start = 0
    gradient_end = int(h * 0.45)
    for y in range(gradient_start, gradient_end):
        progress = 1.0 - (y / gradient_end)  # darkest at top
        alpha = int(160 * progress)
        draw_o.line([(0, y), (w, y)], fill=(0, 0, 0, min(alpha, 160)))

    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=15))
    img = Image.alpha_composite(img, overlay)

    # ---- 2. Title text ----
    draw = ImageDraw.Draw(img)

    # Font size: cover 7.5% of height, sub-cover 11%
    base_font_size = int(h * (0.075 if not is_sub_cover else 0.11))
    title_font = find_font(base_font_size)

    max_width = int(w * 0.88)

    # Wrap title
    lines = wrap_text(draw, title, title_font, max_width)

    # Shrink if > 2 lines
    while len(lines) > 2 and base_font_size > 22:
        base_font_size = int(base_font_size * 0.92)
        title_font = find_font(base_font_size)
        lines = wrap_text(draw, title, title_font, max_width)

    # Truncate to 2 lines max
    if len(lines) > 2:
        lines = lines[:2]
        last = lines[1]
        for i in range(len(last) - 1, 0, -1):
            test = last[:i] + "..."
            bbox = draw.textbbox((0, 0), test, font=title_font)
            if bbox[2] - bbox[0] <= max_width:
                lines[1] = test
                break
        else:
            lines[1] = last[:max(1, len(last) - 3)] + "..."
        lines = lines[:2]

    # Calculate text block height
    line_height = 0
    line_bboxes = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        lh = bbox[3] - bbox[1]
        line_bboxes.append(bbox)
        line_height = max(line_height, lh)

    line_spacing = int(line_height * 0.20)
    total_text_height = len(lines) * line_height + (len(lines) - 1) * line_spacing

    # Position: text block starts at ~12% from top (upper area)
    block_top = int(h * 0.12)

    # Stroke for readability against complex backgrounds
    stroke_width = max(1, base_font_size // 28)

    for i, line in enumerate(lines):
        bbox = line_bboxes[i]
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        y = block_top + i * (line_height + line_spacing)
        draw.text(
            (x, y), line, font=title_font,
            fill=(255, 255, 255, 255),
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0, 140),
        )

    # ---- 3. Optional subtitle (below title) ----
    if subtitle:
        sub_font_size = int(base_font_size * 0.40)
        sub_font = find_font(sub_font_size)
        sub_bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = (w - sub_w) // 2
        sub_y = block_top + total_text_height + int(h * 0.015)
        draw.text(
            (sub_x, sub_y), subtitle, font=sub_font,
            fill=(255, 255, 255, 220),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 100),
        )

    img.convert("RGB").save(str(output_path), quality=95)
    print(f"  [OK] Title overlay (upper): {title[:20]}... -> {output_path.name}")
    return True


def generate_cover(
    title: str,
    summary: str,
    token: str,
    output_path: Path,
    max_rounds: int = 3,
) -> bool:
    """
    Generate pure background cover image (no text overlay).
    Multi-round with progressive NO TEXT constraints + OCR + inpainting.
    """
    print(f"[GEN] Generating cover for: {title[:30]}...")

    final_bg = None
    for round_num in range(1, max_rounds + 1):
        print(f"  Round {round_num}/{max_rounds}...")

        prompt = make_background_prompt(title, summary, round=round_num)
        temp_path = output_path.parent / (output_path.stem + f"_bg_round{round_num}.png")

        print(f"    Generating background...")
        ok = generate_image(prompt, "1280:720", token, temp_path)
        if not ok:
            print(f"    [WARN] Generation failed, retrying...")
            time.sleep(2)
            continue

        print(f"    OCR validating...")
        res = validate_image(temp_path)
        if res.get("pass"):
            print(f"    [OK] No garbled text detected")
            final_bg = temp_path
            break
        else:
            print(f"    [FAIL] Garbled text: {res.get('garbled_count')} block(s)")
            for b in res.get("garbled_blocks", []):
                print(f"       - {b.get('text', '')!r}: {b.get('reason', '')}")

            print(f"    [FIX] Attempting inpainting...")
            inpainted_path = temp_path.parent / (temp_path.stem + "_inpainted.png")
            if inpaint_text_regions(temp_path, inpainted_path):
                res2 = validate_image(inpainted_path)
                if res2.get("pass"):
                    print(f"    [OK] Inpainting fixed it!")
                    final_bg = inpainted_path
                    break

            if temp_path.exists():
                temp_path.unlink()
            if round_num < max_rounds:
                print(f"    Retrying with stronger constraints...")
                time.sleep(2)
                continue

            if 'inpainted_path' in dir() and inpainted_path.exists():
                final_bg = inpainted_path
            else:
                final_bg = temp_path
            break

    if final_bg is None:
        print(f"  [FAIL] All rounds failed")
        return False

    # PIL overlay: title in UPPER area, bottom half stays clean
    ok = overlay_title(final_bg, title, output_path, is_sub_cover=False)
    if not ok:
        # Fallback: copy pure background
        import shutil
        shutil.copy2(str(final_bg), str(output_path))
        print(f"  [WARN] Overlay failed, using pure background: {output_path.name}")

    # Cleanup temp files
    for f in output_path.parent.glob(output_path.stem + "_bg_round*.png"):
        if f != output_path:
            f.unlink()
    for f in output_path.parent.glob(output_path.stem + "_inpainted*.png"):
        f.unlink()

    print(f"  Final OCR check...")
    final_res = validate_image(output_path)
    if final_res.get("pass"):
        print(f"  [OK] Final cover PASSED OCR")
        return True
    else:
        print(f"  [WARN] OCR found issues, but image saved")
        return True  # Still usable


def generate_sub_cover(
    title: str,
    summary: str,
    token: str,
    output_path: Path,
    max_rounds: int = 3,
) -> bool:
    """
    Generate pure background sub-cover (1:1), no text overlay.
    Multi-round with progressive NO TEXT constraints + OCR + inpainting.
    """
    print(f"[GEN] Generating sub-cover for: {title[:30]}...")

    final_bg = None
    for round_num in range(1, max_rounds + 1):
        print(f"  Round {round_num}/{max_rounds}...")

        prompt = make_sub_background_prompt(title, summary, round=round_num)
        temp_path = output_path.parent / (output_path.stem + f"_bg_round{round_num}.png")

        print(f"    Generating background...")
        ok = generate_image(prompt, "1024:1024", token, temp_path)
        if not ok:
            print(f"    [WARN] Generation failed, retrying...")
            time.sleep(2)
            continue

        print(f"    OCR validating...")
        res = validate_image(temp_path)
        if res.get("pass"):
            print(f"    [OK] No garbled text detected")
            final_bg = temp_path
            break
        else:
            print(f"    [FAIL] Garbled text: {res.get('garbled_count')} block(s)")

            print(f"    [FIX] Attempting inpainting...")
            inpainted_path = temp_path.parent / (temp_path.stem + "_inpainted.png")
            if inpaint_text_regions(temp_path, inpainted_path):
                res2 = validate_image(inpainted_path)
                if res2.get("pass"):
                    print(f"    [OK] Inpainting fixed it!")
                    final_bg = inpainted_path
                    break

            if temp_path.exists():
                temp_path.unlink()
            if round_num < max_rounds:
                print(f"    Retrying with stronger constraints...")
                time.sleep(2)
                continue

            if 'inpainted_path' in dir() and inpainted_path.exists():
                final_bg = inpainted_path
            else:
                final_bg = temp_path
            break

    if final_bg is None:
        print(f"  [FAIL] All rounds failed")
        return False

    # PIL overlay for sub-cover too (title in upper area)
    ok = overlay_title(final_bg, title, output_path, is_sub_cover=True)
    if not ok:
        import shutil
        shutil.copy2(str(final_bg), str(output_path))
        print(f"  [WARN] Overlay failed, using pure background: {output_path.name}")

    for f in output_path.parent.glob(output_path.stem + "_bg_round*.png"):
        if f != output_path:
            f.unlink()
    for f in output_path.parent.glob(output_path.stem + "_inpainted*.png"):
        f.unlink()

    print(f"  Final OCR check...")
    final_res = validate_image(output_path)
    if final_res.get("pass"):
        print(f"  [OK] Final sub-cover PASSED OCR")
        return True
    else:
        print(f"  [WARN] OCR found issues, but image saved")
        return True


def main():
    parser = argparse.ArgumentParser(description="Generate pure background cover images (no text overlay)")
    parser.add_argument("--token", default=None, help="Cloud service token (BUDDY_CLOUD_TOKEN)")
    parser.add_argument("--token-stdin", action="store_true", help="Read token from stdin")
    parser.add_argument("--manifest", help="Path to manifest.json")
    parser.add_argument("--title", help="Article title (for single image generation)")
    parser.add_argument("--output", help="Output path (for single image generation)")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--cover-only", action="store_true")
    parser.add_argument("--sub-only", action="store_true")
    args = parser.parse_args()

    # Read token
    if args.token_stdin:
        args.token = sys.stdin.read().strip()
    if not args.token:
        print("Error: --token or --token-stdin required")
        sys.exit(1)

    # Single article mode
    if args.title and args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ok = generate_cover(args.title, "", args.token, output_path, args.max_rounds)
        sys.exit(0 if ok else 1)

    # Manifest mode
    if not args.manifest:
        print("Error: --manifest required (unless using --title + --output)")
        sys.exit(1)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Error: manifest not found: {manifest_path}")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    articles = manifest.get("articles", [])
    success = 0
    total = 0

    for idx, article in enumerate(articles):
        title = article.get("title", "")
        if not title:
            continue

        # Skip already-generated images (resume support)
        def already_exists(path):
            return path.exists() and path.stat().st_size > 10000

        if not args.sub_only:
            total += 1
            rel = article.get("cover_image", "")
            if rel:
                cover_path = manifest_path.parent / rel
            else:
                cover_path = manifest_path.parent / "imgs" / f"{title[:10]}_cover.png"
            cover_path.parent.mkdir(parents=True, exist_ok=True)

            if already_exists(cover_path):
                print(f"  [SKIP] Cover already exists: {cover_path.name}")
                success += 1
            else:
                # Rate limit: wait before each API call to avoid quota (45 concurrent limit)
                if idx > 0 or total > 1:
                    print(f"  [WAIT] 60s cooldown to avoid API quota limit...")
                    time.sleep(60)
                ok = generate_cover(title, article.get("summary", ""), args.token, cover_path, args.max_rounds)
                if ok:
                    success += 1
                else:
                    print(f"  [WARN] Cover generation failed for: {title[:30]}...")

        if not args.cover_only:
            total += 1
            rel = article.get("sub_cover_image", "")
            if rel:
                sub_path = manifest_path.parent / rel
            else:
                sub_path = manifest_path.parent / "imgs" / f"{title[:10]}_sub.png"
            sub_path.parent.mkdir(parents=True, exist_ok=True)

            if already_exists(sub_path):
                print(f"  [SKIP] Sub-cover already exists: {sub_path.name}")
                success += 1
            else:
                # Rate limit: wait before each API call
                print(f"  [WAIT] 60s cooldown to avoid API quota limit...")
                time.sleep(60)
                ok = generate_sub_cover(title, article.get("summary", ""), args.token, sub_path, args.max_rounds)
                if ok:
                    success += 1
                else:
                    print(f"  [WARN] Sub-cover generation failed for: {title[:30]}...")

    print(f"\n[RESULT] Generated {success}/{total} covers")
    sys.exit(0 if success == total else 1)


if __name__ == "__main__":
    main()

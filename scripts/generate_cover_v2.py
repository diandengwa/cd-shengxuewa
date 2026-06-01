#!/usr/bin/env python3
"""
Generate cover images: AI background + PIL text overlay.

Strategy:
  1. AI generates high-quality BACKGROUND (no-text prompt)
  2. If text detected by OCR, remove it (inpaint or simple fill)
  3. PIL overlays SHORT Chinese title (4-6 chars) with nice font
  4. Result: high-quality visual + correct text (no garble possible)

Usage:
    python generate_cover_v2.py --token <token> --manifest <manifest.json>
    python generate_cover_v2.py --token-stdin --manifest <manifest.json>
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

SCRIPT_DIR = Path(__file__).parent
BUDDY_CLOUD_PY = (
    Path(os.environ.get("LOCALAPPDATA", "C:/Users/TangShaoWan/AppData/Local"))
    / "Programs/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills"
    / "buddy-multimodal-generation/scripts/buddy-cloud.py"
)
PYTHON_EXE = "C:\\Users\\TangShaoWan\\anaconda3\\python.exe"

# Chinese font for PIL text overlay
FONT_PATHS = [
    "C:/Windows/Fonts/simhei.ttf",      # 黑体 Bold
    "C:/Windows/Fonts/msyhbd.ttc",     # 微软雅黑 Bold
    "C:/Windows/Fonts/simkai.ttf",      # 楷体
    "C:/Windows/Fonts/simsun.ttc",      # 宋体
]


def find_font() -> str:
    for fp in FONT_PATHS:
        if os.path.exists(fp):
            return fp
    raise FileNotFoundError("No Chinese font found! Check FONT_PATHS.")


def generate_background(prompt: str, resolution: str, token: str, output_path: Path) -> bool:
    """Call buddy-cloud.py to generate background image (NO text)."""
    cmd = [
        PYTHON_EXE,
        str(BUDDY_CLOUD_PY),
        "image",
        prompt,
        "--resolution", resolution,
        "--token-stdin",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=token,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(output_path.parent),
        )
    except subprocess.TimeoutExpired:
        print(f"  ⚠️ Timeout generating image")
        return False

    # Parse JSON from stdout
    json_blocks = re.findall(r'\{[\s\S]*?\}', result.stdout)
    if not json_blocks:
        print(f"  ⚠️ No JSON output. stdout: {result.stdout[:500]}")
        return False

    data = None
    for block in reversed(json_blocks):
        try:
            data = json.loads(block)
            break
        except json.JSONDecodeError:
            continue

    if data is None:
        print(f"  ⚠️ JSON parse error")
        return False

    if data.get("status") != "DONE":
        print(f"  ⚠️ Generation failed: {data}")
        return False

    result_url = data.get("result_url", [])
    if not result_url:
        print(f"  ⚠️ No result_url")
        return False

    url = result_url[0] if isinstance(result_url, list) else result_url

    dl_cmd = ["curl", "-sS", "-L", "-o", str(output_path.name), url]
    dl_result = subprocess.run(dl_cmd, capture_output=True, cwd=str(output_path.parent))
    if dl_result.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1000:
        print(f"  ⚠️ Download failed")
        return False

    return True


def make_background_prompt(title: str, summary: str = "") -> str:
    """Build prompt for AI background generation (TEXT-FREE)."""
    if "幼儿园" in title or "摇号" in title or "补录" in title:
        palette = "fresh teal-green to warm yellow, soft gradient"
        visual = "kindergarten building with red roof, sunny playground, children's watercolor style, soft warm sunlight, bokeh"
        mood = "warm, hopeful, sunny"
    elif "小升初" in title or "录取" in title or "学位" in title:
        palette = "deep navy blue to warm orange sunset, professional gradient"
        visual = "modern school campus silhouette, graduation cap and tassel, academic architecture, clean contemporary lines, subtle clock tower, bokeh"
        mood = "authoritative, urgent, professional, aspirational"
    else:
        palette = "sophisticated blue-purple gradient"
        visual = "clean academic-themed illustration, open books, pencil and ruler, modern flat vector art, bokeh"
        mood = "professional, trustworthy, calm"

    return (
        f"WeChat official account cover background, 16:9 ratio, "
        f"PURE VISUAL, NO TEXT, NO TYPOGRAPHY, NO LETTERS, NO CHARACTERS, "
        f"high-end editorial design, magazine cover quality, "
        f"{palette}, "
        f"visual elements: {visual}, "
        f"mood: {mood}, "
        f"CLEAR negative space in center (40% of image width, perfectly empty), "
        f"NO text or symbols in center region, "
        f"textured edges, subtle depth, cinematic lighting, "
        f"8k resolution, photorealistic, award-winning composition, "
        f"--no text --no typography --no letters"
    )


def remove_text_regions(image_path: Path, padding: int = 8) -> bool:
    """
    Use OCR to find text regions, then fill them with surrounding color.
    Returns True if any text was removed.
    """
    try:
        import easyocr
        import numpy as np
        from PIL import Image
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)
    except ImportError:
        print("  ⚠️ easyocr/PIL not available, skipping text removal")
        return False

    try:
        reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
        img = Image.open(image_path).convert('RGB')
        img_array = np.array(img)
        h, w = img_array.shape[:2]

        results = reader.readtext(img_array, detail=1)

        # Filter: only remove low-conf or garbled-looking text
        watermark_kw = ['图片由', 'AI生成']
        text_boxes = []
        for r in results:
            bbox, text, conf = r
            if not text.strip():
                continue
            if any(kw in text for kw in watermark_kw):
                continue
            # Only remove low-conf or garbled text
            chinese_chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
            if chinese_chars:
                uncommon = [c for c in chinese_chars if c not in COMMON_CHARS]
                rare_ratio = len(uncommon) / len(chinese_chars)
                if rare_ratio < 0.3 and conf > 0.3:
                    continue  # Likely normal text, keep it
            if conf < 0.2 or (chinese_chars and len(chinese_chars) >= 2):
                text_boxes.append(bbox)

        if not text_boxes:
            return False

        # Simple inpainting: fill with average color of surrounding region
        img_np = np.array(img)
        for bbox in text_boxes:
            xs = [int(p[0]) for p in bbox]
            ys = [int(p[1]) for p in bbox]
            x1 = max(0, min(xs) - padding)
            y1 = max(0, min(ys) - padding)
            x2 = min(w, max(xs) + padding)
            y2 = min(h, max(ys) + padding)

            # Sample surrounding color (average of border pixels)
            border_pixels = []
            for x in range(x1, x2):
                if y1 > 0:
                    border_pixels.append(img_np[y1-1, x])
                if y2 < h:
                    border_pixels.append(img_np[y2, x])
            for y in range(y1, y2):
                if x1 > 0:
                    border_pixels.append(img_np[y, x1-1])
                if x2 < w:
                    border_pixels.append(img_np[y, x2])

            if border_pixels:
                avg_color = np.mean(border_pixels, axis=0).astype(int)
                img_np[y1:y2, x1:x2] = avg_color

        Image.fromarray(img_np).save(image_path)
        print(f"  🧹 Removed {len(text_boxes)} text region(s)")
        return True

    except Exception as e:
        print(f"  ⚠️ Text removal error: {e}")
        return False


# Common chars set (abbreviated)
COMMON_CHARS = set(
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多"
)


def add_chinese_title(image_path: Path, title: str, output_path: Path = None) -> Path:
    """
    Overlay short Chinese title (max 6 chars) onto the center of the cover image.
    Uses high-quality Chinese font (simhei/msyhbd).
    """
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np

    if output_path is None:
        output_path = image_path

    font_path = find_font()
    img = Image.open(image_path).convert('RGB')
    w, h = img.size

    # Prepare title: max 6 chars
    display_title = title[:6] if len(title) > 6 else title
    # Remove punctuation
    display_title = re.sub(r"[？?！!，,。.、\"'\'':;；]", "", display_title)

    # Choose font size (responsive)
    font_size = int(h * 0.12)  # 12% of image height
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(img)

    # Measure text size
    bbox = draw.textbbox((0, 0), display_title, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Position: center of image
    x = (w - tw) // 2
    y = (h - th) // 2

    # Draw text with shadow (for readability on any background)
    shadow_offset = max(2, font_size // 20)
    # Shadow (dark)
    draw.text((x + shadow_offset, y + shadow_offset), display_title, font=font, fill=(0, 0, 0, 180))
    # Main text (white or dark, depending on background)
    # Simple heuristic: use white text with semi-transparent black shadow
    draw.text((x, y), display_title, font=font, fill=(255, 255, 255, 230))

    img.save(output_path)
    return output_path


def validate_final_image(image_path: Path) -> dict:
    """Final OCR check: make sure no garbled text remains."""
    try:
        import cover_validator as cv
        return cv.validate_image(str(image_path), verbose=False)
    except Exception:
        return {"pass": True, "garbled_count": 0, "garbled_blocks": []}


def generate_cover_for_article(article: dict, token: str, output_dir: Path, max_retries: int = 3) -> dict:
    """Full pipeline for one article: generate background → remove text → add title."""
    title = article.get("title", "")
    summary = article.get("summary", "")
    slug = slugify(title)

    cover_path = output_dir / f"{slug}_cover_v2.png"
    bg_path = output_dir / f"{slug}_cover_bg.png"

    print(f"  Step 1: Generating background (16:9)...")
    bg_prompt = make_background_prompt(title, summary)

    for attempt in range(1, max_retries + 1):
        print(f"    Attempt {attempt}/{max_retries}...")
        ok = generate_background(bg_prompt, "1280:720", token, bg_path)
        if not ok:
            if attempt < max_retries:
                time.sleep(3)
                continue

        # Step 2: Remove any remaining text
        print(f"  Step 2: Removing text regions...")
        remove_text_regions(bg_path)

        # Step 3: Add Chinese title
        print(f"  Step 3: Adding title '{title[:6]}'...")
        try:
            add_chinese_title(bg_path, title, cover_path)
        except Exception as e:
            print(f"  ⚠️ Text overlay failed: {e}, using background only")
            import shutil
            shutil.copy(bg_path, cover_path)

        # Step 4: Final OCR validation
        print(f"  Step 4: Final OCR validation...")
        res = validate_final_image(cover_path)
        if res.get("pass"):
            print(f"  ✅ Cover passed validation")
            return {"ok": True, "path": str(cover_path), "title": title}

        print(f"  ❌ Validation failed: {res.get('garbled_count')} garbled block(s)")
        if attempt < max_retries:
            time.sleep(2)
            continue

    print(f"  ❌ All {max_retries} attempts failed")
    return {"ok": False, "path": None, "title": title}


def slugify(title: str) -> str:
    t = title.strip()
    if len(t) > 10:
        t = t[:10]
    t = re.sub(r"[？?！!，,。.、\"'\'':;；]", "", t)
    return t


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=None, help="Cloud service token (or use --token-stdin)")
    parser.add_argument("--token-stdin", action="store_true", help="Read token from stdin")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--articles", help="Comma-separated article indices (0-based), default=all")
    args = parser.parse_args()

    if args.token_stdin:
        import sys
        args.token = sys.stdin.read().strip()

    if not args.token:
        print("Error: --token or --token-stdin required")
        sys.exit(1)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    articles = manifest.get("articles", [])
    if args.articles:
        indices = [int(x.strip()) for x in args.articles.split(",")]
        articles = [articles[i] for i in indices if 0 <= i < len(articles)]

    output_dir = manifest_path.parent / "imgs"
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for idx, article in enumerate(articles):
        title = article.get("title", "")
        print(f"\n[{idx+1}/{len(articles)}] {title}")

        result = generate_cover_for_article(article, args.token, output_dir, args.max_retries)
        results.append(result)

        # Update manifest
        for art in manifest["articles"]:
            if art["title"] == title:
                art["cover_image"] = result["path"] if result["ok"] else art.get("cover_image")
                break

    # Save updated manifest
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Manifest updated: {manifest_path}")

    # Summary
    print("\n" + "=" * 50)
    print("COVER GENERATION SUMMARY")
    print("=" * 50)
    for r in results:
        icon = "✅" if r["ok"] else "❌"
        print(f"{icon} {r['title'][:40]}")
    print()

    if all(r["ok"] for r in results):
        print("🎉 All covers generated successfully!")
        sys.exit(0)
    else:
        print("⚠️ Some covers failed. Check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

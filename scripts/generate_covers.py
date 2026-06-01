#!/usr/bin/env python3
"""
Auto-generate cover + sub-cover images with OCR validation loop.

Uses Tencent Hunyuan (via buddy-cloud.py) for image generation,
easyocr for Chinese text quality validation.

Strategy (2026-05-24 update):
  - Cover (16:9): English headline + rich visual design (no Chinese garble risk)
  - Sub-cover (1:1): Simple Chinese short text (user confirmed OK)

Usage:
    python generate_covers.py --token <token> --manifest <manifest.json>
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Add script dir to path for importing cover_validator
sys.path.insert(0, str(Path(__file__).parent))

SCRIPT_DIR = Path(__file__).parent
BUDDY_CLOUD_PY = (
    Path(os.environ.get("LOCALAPPDATA", "C:/Users/TangShaoWan/AppData/Local"))
    / "Programs/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills"
    / "buddy-multimodal-generation/scripts/buddy-cloud.py"
)
PYTHON_EXE = "C:\\Users\\TangShaoWan\\anaconda3\\python.exe"


# ---- Title translation table (Chinese -> English keywords) ----
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


def chinese_to_english_keywords(title: str) -> str:
    """Convert Chinese title to English design keywords."""
    title_lower = title.lower()
    keywords = []
    for k, v in TITLE_EN.items():
        if k in title:
            keywords.append(v)
    if not keywords:
        # Fallback: use first 4-6 chars
        short = title[:6]
        return f"EDUCATION GUIDE: {short}"
    return " | ".join(keywords[:3])


def generate_image(prompt: str, resolution: str, token: str, output_path: Path) -> bool:
    """Call buddy-cloud.py to generate an image. Returns True on success."""
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

    # Parse JSON from stdout (buddy-cloud.py interleaves INFO logs with JSON)
    json_blocks = re.findall(r'\{[\s\S]*?\}', result.stdout)
    if not json_blocks:
        print(f"  ⚠️ No JSON output. stdout: {result.stdout[:500]}")
        return False

    # Try parsing each block from last to first
    data = None
    for block in reversed(json_blocks):
        try:
            data = json.loads(block)
            break
        except json.JSONDecodeError:
            continue

    if data is None:
        print(f"  ⚠️ JSON parse error on all {len(json_blocks)} candidate block(s)")
        return False

    if data.get("status") != "DONE":
        print(f"  ⚠️ Generation failed: {data}")
        return False

    result_url = data.get("result_url", [])
    if not result_url:
        print(f"  ⚠️ No result_url in response")
        return False

    url = result_url[0] if isinstance(result_url, list) else result_url

    # Download image
    dl_cmd = ["curl", "-sS", "-L", "-o", str(output_path.name), url]
    dl_result = subprocess.run(dl_cmd, capture_output=True, cwd=str(output_path.parent))
    if dl_result.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1000:
        print(f"  ⚠️ Download failed or file too small")
        return False

    return True


def validate_image(image_path: Path) -> dict:
    """Run cover_validator on image. Returns result dict."""
    import cover_validator as cv
    return cv.validate_image(str(image_path), verbose=False)


def make_cover_prompt(title: str, summary: str = "", simplify: bool = False) -> str:
    """
    Build a high-quality prompt for cover image (16:9).
    TEXT-FREE: no text in image to avoid garbling.
    WeChat displays article title below cover anyway.
    """
    # Detect topic color scheme and visual elements
    if "幼儿园" in title or "摇号" in title or "补录" in title:
        palette = "fresh teal-green to warm yellow gradient"
        visual = "kindergarten building with red roof, sunny playground, children's watercolor style, soft warm sunlight"
        mood = "warm, hopeful, sunny, gentle"
    elif "小升初" in title or "录取" in title or "学位" in title:
        palette = "deep navy blue to warm orange sunset gradient"
        visual = "modern school campus silhouette, graduation cap and tassel, academic architecture, clean contemporary lines, subtle clock tower"
        mood = "authoritative, urgent, professional, aspirational"
    else:
        palette = "sophisticated blue-purple gradient"
        visual = "clean academic-themed illustration, open books, pencil and ruler, modern flat vector art"
        mood = "professional, trustworthy, calm"

    if simplify:
        return (
            f"WeChat official account cover image, 16:9 ratio, "
            f"minimalist design, {palette} background, "
            f"NO text, NO typography, NO letters, NO characters in image, "
            f"simple geometric shapes, plenty of white space, "
            f"clean and elegant"
        )

    return (
        f"WeChat official account cover image, 16:9 ratio, "
        f"high-end editorial design, magazine cover quality, "
        f"{palette} background with subtle paper texture and depth, "
        f"visual elements: {visual}, "
        f"NO text, NO typography, NO letters, NO characters in the image, "
        f"pure visual design, artistic and sophisticated, "
        f"mood: {mood}, "
        f"cinematic lighting, bokeh background, sharp focus on subject, "
        f"premium education content aesthetic, "
        f"8k resolution, photorealistic, award-winning composition"
    )


def make_sub_prompt(title: str, summary: str = "", simplify: bool = False) -> str:
    """Build a prompt for sub-cover image (1:1). Keep simple as user confirmed.
    CRITICAL: Do NOT put Chinese title text in prompt (triggers content filter).
    WeChat displays title separately for sub-articles, image doesn't need text.
    """
    # Use English keywords only to avoid content filter
    en_kw = chinese_to_english_keywords(title)

    if simplify:
        return (
            f"Square social media thumbnail, 1:1 ratio, "
            f"clean gradient background, minimalist, "
            f"NO text, NO typography, NO characters, "
            f"plenty of white space, suitable for WeChat sub-article"
        )

    return (
        f"Square social media thumbnail, 1:1 ratio, "
        f"elegant gradient background with subtle bokeh, "
        f"minimalist flat design, "
        f"NO text, NO typography, NO characters in image, "
        f"clean and modern, suitable for WeChat sub-article thumbnail, "
        f"high quality, 4k resolution"
    )


def generate_with_retry(
    prompt: str,
    resolution: str,
    token: str,
    output_path: Path,
    max_retries: int = 3,
) -> bool:
    """Generate image with OCR validation loop."""
    for attempt in range(1, max_retries + 1):
        print(f"  Attempt {attempt}/{max_retries}...")
        ok = generate_image(prompt, resolution, token, output_path)
        if not ok:
            if attempt < max_retries:
                print(f"  Generation failed, retrying with simplified prompt...")
                # Simplify prompt for retry
                prompt = make_cover_prompt(
                    re.search(r"'([^']+)'", prompt).group(1) if "'" in prompt else "",
                    simplify=True,
                )
                time.sleep(2)
            continue

        # Validate
        print(f"  OCR validating...")
        res = validate_image(output_path)
        if res.get("pass"):
            print(f"  ✅ Passed OCR check")
            return True

        print(f"  ❌ Garbled text detected ({res['garbled_count']} block(s)):")
        for b in res["garbled_blocks"]:
            print(f"     • {b['text']!r} → {b['reason']}")

        if attempt < max_retries:
            print(f"  Retrying with simplified prompt...")
            # Extract title from prompt
            m = re.search(r"'([^']+)'", prompt)
            title = m.group(1) if m else ""
            prompt = make_cover_prompt(title, simplify=True)
            time.sleep(2)

    print(f"  ❌ All {max_retries} attempts failed.")
    return False


def slugify(title: str) -> str:
    """Create a short slug from title."""
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
    parser.add_argument("--cover-only", action="store_true", help="Only regenerate cover images (16:9)")
    parser.add_argument("--sub-only", action="store_true", help="Only regenerate sub-cover images (1:1)")
    args = parser.parse_args()

    # Read token from stdin if requested
    if args.token_stdin:
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
    paths = {}  # Store paths for results

    for idx, article in enumerate(articles):
        title = article.get("title", "")
        slug = slugify(title)
        summary = article.get("summary", "")
        print(f"\n[{idx+1}/{len(articles)}] {title}")

        cover_ok = True
        sub_ok = True
        cover_path = output_dir / f"{slug}_cover.png"
        sub_path = output_dir / f"{slug}_sub.png"
        paths[slug] = {"cover": cover_path, "sub": sub_path}

        # ---- Cover image (16:9) ----
        if not args.sub_only:
            print(f"  Generating COVER (16:9) -> {cover_path.name}")
            cover_prompt = make_cover_prompt(title, summary, simplify=False)
            print(f"  Prompt preview: {cover_prompt[:120]}...")
            cover_ok = generate_with_retry(
                cover_prompt, "1280:720", args.token, cover_path, args.max_retries
            )

        # ---- Sub-cover image (1:1) ----
        if not args.cover_only:
            print(f"  Generating SUB-COVER (1:1) -> {sub_path.name}")
            sub_prompt = make_sub_prompt(title, summary, simplify=False)
            print(f"  Prompt preview: {sub_prompt[:120]}...")
            sub_ok = generate_with_retry(
                sub_prompt, "1024:1024", args.token, sub_path, args.max_retries
            )

        results.append({
            "title": title,
            "cover": str(cover_path) if cover_ok else None,
            "sub": str(sub_path) if sub_ok else None,
            "cover_ok": cover_ok,
            "sub_ok": sub_ok,
        })

    # Summary
    print("\n" + "=" * 50)
    print("GENERATION SUMMARY")
    print("=" * 50)
    all_ok = True
    for r in results:
        c = "✅" if r["cover_ok"] else "❌"
        s = "✅" if r["sub_ok"] else "❌"
        print(f"{c} Cover  | {s} Sub    | {r['title'][:30]}")
        if not r["cover_ok"] or not r["sub_ok"]:
            all_ok = False

    if all_ok:
        print("\n🎉 All images generated and passed OCR validation!")
        sys.exit(0)
    else:
        print("\n⚠️ Some images failed. Check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

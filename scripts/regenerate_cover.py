#!/usr/bin/env python3
"""
Regenerate cover images with progressive text-suppression prompts.
Long-term solution: prevent garbled text at generation time,
instead of fixing it post-hoc.

Strategy:
  Round 1: Normal prompt (high quality)
  Round 2: + "STRICTLY NO TEXT/LETTERS/SYMBOLS anywhere"
  Round 3: + "ABSOLUTELY TEXT-FREE, blank signs, no writing"
  OCR validates each round; stops when pass or max rounds reached.

Usage:
  python regenerate_cover.py --token <token> --manifest <path> [--cover-only | --sub-only]
  python regenerate_cover.py --image-prompt "prompt" --output <path> --token <token>
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ---- Paths ----
SCRIPT_DIR = Path(__file__).parent
BUDDY_CLOUD_PY = (
    Path(os.environ.get("LOCALAPPDATA", "C:/Users/TangShaoWan/AppData/Local"))
    / "Programs/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills"
    / "buddy-multimodal-generation/scripts/buddy-cloud.py"
)
PYTHON_EXE = "C:\\Users\\TangShaoWan\\anaconda3\\python.exe"

# ---- Title translation ----
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
    title_lower = title.lower()
    keywords = []
    for k, v in TITLE_EN.items():
        if k in title:
            keywords.append(v)
    if not keywords:
        short = title[:6]
        return f"EDUCATION GUIDE: {short}"
    return " | ".join(keywords[:3])


# ---- Prompt constructors (progressive text suppression) ----

def make_cover_prompt(title: str, summary: str = "", round: int = 1) -> str:
    """
    Build cover prompt with progressive text suppression.
    Round 1: normal (high quality)
    Round 2: + strict no-text instruction
    Round 3: + absolute text-free + blank signs
    """
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

    # Base prompt (high quality)
    base = (
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

    if round >= 2:
        base += (
            ". STRICTLY NO TEXT, NO LETTERS, NO NUMBERS, NO SYMBOLS "
            "ANYWHERE IN THE IMAGE. All signs, billboards, and objects must be "
            "completely blank. This is a strict requirement."
        )

    if round >= 3:
        base += (
            " ABSOLUTELY TEXT-FREE IMAGE. ZERO text, ZERO letters, ZERO numbers, "
            "ZERO symbols. All signs are blank. All surfaces are clean. "
            "NO WRITING OF ANY KIND. This is the MOST IMPORTANT requirement."
        )

    return base


def make_sub_prompt(title: str, summary: str = "", round: int = 1) -> str:
    """Build sub-cover prompt (1:1) with progressive text suppression."""
    en_kw = chinese_to_english_keywords(title)

    base = (
        f"Square social media thumbnail, 1:1 ratio, "
        f"elegant gradient background with subtle bokeh, "
        f"minimalist flat design, "
        f"NO text, NO typography, NO characters in image, "
        f"clean and modern, suitable for WeChat sub-article thumbnail, "
        f"high quality, 4k resolution"
    )

    if round >= 2:
        base += (
            ". STRICTLY NO TEXT ANYWHERE. Blank design, no writing, no symbols."
        )

    if round >= 3:
        base += (
            " ABSOLUTELY NO TEXT, NO LETTERS, NO NUMBERS in any form. "
            "Completely text-free image."
        )

    return base


# ---- Image generation ----

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


# ---- OCR validation ----

def validate_image(image_path: str) -> dict:
    """Run cover_validator on image. Returns result dict."""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        import cover_validator as cv
        return cv.validate_image(image_path, verbose=False)
    except Exception as e:
        print(f"  ⚠️ Validator error: {e}")
        return {"pass": False, "garbled_count": 99}


# ---- Main logic ----

def regenerate_one(title: str, summary: str, output_path: Path,
                  token: str, resolution: str, max_rounds: int = 3,
                  is_sub: bool = False) -> bool:
    """
    Regenerate one cover image with progressive prompt strengthening.
    Returns True if a valid image was saved.
    """
    print(f"\n{'='*60}")
    print(f"Regenerating: {title}")
    print(f"Output: {output_path}")
    print(f"{'='*60}")

    best_result = None
    best_score = -1  # lower garbled_count = better

    for rnd in range(1, max_rounds + 1):
        print(f"\n--- Round {rnd}/{max_rounds} ---")

        # Build prompt for this round
        if is_sub:
            prompt = make_sub_prompt(title, summary, round=rnd)
        else:
            prompt = make_cover_prompt(title, summary, round=rnd)

        print(f"  Prompt preview: {prompt[:120]}...")

        # Generate
        ok = generate_image(prompt, resolution, token, output_path)
        if not ok:
            print(f"  ❌ Generation failed, retrying in 3s...")
            time.sleep(3)
            continue

        # Validate
        print(f"  OCR validating...")
        res = validate_image(str(output_path))

        garbled = res.get("garbled_count", 0)
        total = res.get("total_blocks", 0)

        if res.get("pass"):
            print(f"  ✅ Round {rnd}: PASSED! (0/{total} garbled)")
            return True
        else:
            print(f"  ❌ Round {rnd}: FAILED ({garbled}/{total} garbled blocks)")
            for b in res.get("garbled_blocks", []):
                print(f"     • {b['text']!r}: {b['reason']}")

            # Save best result so far
            if best_result is None or garbled < best_score:
                import shutil
                best_result = output_path.with_suffix(".best" + output_path.suffix)
                shutil.copy(output_path, best_result)
                best_score = garbled

        # Wait before next round (rate limiting)
        if rnd < max_rounds:
            time.sleep(2)

    # All rounds failed: use best result
    print(f"\n  ⚠️ All {max_rounds} rounds failed.")
    if best_result and best_result.exists():
        import shutil
        shutil.copy(best_result, output_path)
        print(f"  Using best result ({best_score} garbled blocks remaining)")
        return False
    return False


def slugify(title: str) -> str:
    """Create a short slug from title."""
    t = title.strip()
    if len(t) > 10:
        t = t[:10]
    t = re.sub(r"[？?！!，,。.\、\"'\'':;；]", "", t)
    return t


# ---- CLI ----

def main():
    parser = argparse.ArgumentParser(description="Regenerate covers with progressive text suppression")
    parser.add_argument("--token", default=None, help="Cloud service token (or use --token-stdin)")
    parser.add_argument("--token-stdin", action="store_true", help="Read token from stdin")
    parser.add_argument("--manifest", default=None, help="Path to manifest.json")
    parser.add_argument("--max-rounds", type=int, default=3, help="Max regeneration rounds (default: 3)")
    parser.add_argument("--cover-only", action="store_true", help="Only regenerate cover images (16:9)")
    parser.add_argument("--sub-only", action="store_true", help="Only regenerate sub-cover images (1:1)")
    parser.add_argument("--image-prompt", default=None, help="Generate from raw prompt (no manifest)")
    parser.add_argument("--output", default=None, help="Output path for raw-prompt mode")
    args = parser.parse_args()

    if args.token_stdin:
        args.token = sys.stdin.read().strip()

    if not args.token:
        print("ERROR: --token or --token-stdin required")
        sys.exit(1)

    # Raw prompt mode
    if args.image_prompt:
        if not args.output:
            print("ERROR: --output required with --image-prompt")
            sys.exit(1)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ok = regenerate_one(
            title="raw-prompt",
            summary="",
            output_path=output_path,
            token=args.token,
            resolution="1280:720",
            max_rounds=args.max_rounds,
            is_sub=False,
        )
        sys.exit(0 if ok else 1)

    # Manifest mode
    if not args.manifest:
        print("ERROR: --manifest required (unless using --image-prompt)")
        parser.print_help()
        sys.exit(2)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    articles = manifest.get("articles", [])
    if not articles:
        print("No articles found in manifest")
        sys.exit(1)

    print(f"Found {len(articles)} article(s) in manifest")

    for i, article in enumerate(articles):
        title = article.get("title", f"Article {i}")
        summary = article.get("summary", "")

        # Determine output paths
        cover_path = Path(article.get("cover_image", ""))
        sub_path = Path(article.get("sub_cover_image", ""))

        # Regenerate cover
        if not args.sub_only:
            if not cover_path or not cover_path.exists():
                print(f"\n[{i+1}/{len(articles)}] Cover: {title}")
                print(f"  ⚠️ cover_image path not found in manifest, skipping")
            else:
                print(f"\n[{i+1}/{len(articles)}] Regenerating cover: {title}")
                regenerate_one(
                    title=title,
                    summary=summary,
                    output_path=cover_path,
                    token=args.token,
                    resolution="1280:720",
                    max_rounds=args.max_rounds,
                    is_sub=False,
                )

        # Regenerate sub-cover
        if args.cover_only:
            continue
        if not args.sub_only and not args.cover_only:
            # Default: do both
            pass

        if not args.cover_only:
            if not sub_path or not sub_path.exists():
                # Try to find or create sub-cover path
                if cover_path:
                    sub_path = cover_path.parent / cover_path.name.replace("_cover", "_sub")
            if not sub_path or not sub_path.exists():
                print(f"  ⚠️ sub_cover_image path not found, skipping")
                continue
            print(f"\n[{i+1}/{len(articles)}] Regenerating sub-cover: {title}")
            regenerate_one(
                title=title,
                summary=summary,
                output_path=sub_path,
                token=args.token,
                resolution="720:720",
                max_rounds=args.max_rounds,
                is_sub=True,
            )

    print(f"\n{'='*60}")
    print("Regeneration complete.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

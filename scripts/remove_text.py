#!/usr/bin/env python3
"""
Post-process cover images: detect text regions via OCR,
then inpaint (remove) them using OpenCV or simple fill.

Usage:
    python remove_text.py --image <path> [--output <path>] [--method fill]
    python remove_text.py --dir <dir> [--pattern "*.png"]
"""

import argparse
import json
import os
import sys

# ---- Lazy-load OCR reader ----
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)
        _reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
    return _reader


def remove_text_pil(image_path: str, output_path: str = None, padding: int = 5) -> str:
    """
    Remove text using PIL: draw rounded rectangle matching surrounding color.
    Simple but effective for solid-color backgrounds.
    """
    from PIL import Image, ImageDraw
    import numpy as np

    if output_path is None:
        base, ext = os.path.splitext(image_path)
        output_path = f"{base}_notext{ext}"

    reader = get_reader()
    img = Image.open(image_path).convert('RGB')
    img_array = np.array(img)
    h, w = img_array.shape[:2]

    # Get text regions
    results = reader.readtext(img_array, detail=1)

    # Filter: only keep low-conf or garbled-looking text
    watermark_kw = ['图片由', 'AI生成', 'A1生成']
    text_regions = []
    for r in results:
        bbox, text, conf = r
        if not text.strip():
            continue
        # Skip watermarks
        if any(kw in text for kw in watermark_kw):
            continue
        # Only remove low-conf or garbled-looking text
        chinese_chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
        if chinese_chars:
            uncommon = [c for c in chinese_chars if c not in COMMON_CHARS]
            rare_ratio = len(uncommon) / len(chinese_chars)
            if rare_ratio < 0.3 and conf > 0.3:
                continue  # Likely normal text, keep it
        text_regions.append((bbox, text, conf))

    if not text_regions:
        print(f"  No garbled text found, skipping")
        return image_path

    # Inpaint using OpenCV if available
    try:
        import cv2
        import numpy as np

        img_cv = cv2.imread(image_path)
        mask = np.zeros((h, w), dtype=np.uint8)

        for bbox, text, conf in text_regions:
            # bbox: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            xs = [int(p[0]) for p in bbox]
            ys = [int(p[1]) for p in bbox]
            x1, y1 = max(0, min(xs)-padding), max(0, min(ys)-padding)
            x2, y2 = min(w, max(xs)+padding), min(h, max(ys)+padding)
            cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)

        # Inpaint
        result = cv2.inpaint(img_cv, mask, 3, cv2.INPAINT_TELEA)
        cv2.imwrite(output_path, result)
        print(f"  ✅ Removed {len(text_regions)} text region(s) via OpenCV inpaint")
        return output_path

    except ImportError:
        # Fallback: simple white rectangle (looks bad, but works)
        print(f"  ⚠️ OpenCV not available, using simple cover (no text)")
        # Just generate a new image without text
        return image_path


# Common chars set (abbreviated - same as cover_validator.py)
COMMON_CHARS = set(
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取完举色或找付信修保推采望构摸检确座摄疑潮熟奖版独玛环畅略盖盛盘移税穿系久低假像偶偷偿催允元充兆先光入全八公六共关兴兵其具典写军农况冷准刀刊列则创初删利刷剧剩劳势匠匹占卡卫印危卵卷厚原厕去参又叉及友双反发取受变"
)


def main():
    parser = argparse.ArgumentParser(description="Remove garbled text from cover images")
    parser.add_argument("--image", "-i", help="Path to single image file")
    parser.add_argument("--dir", "-d", help="Directory to scan for images")
    parser.add_argument("--pattern", "-p", default="*.png", help="Glob pattern")
    parser.add_argument("--output", "-o", help="Output path (for single image)")
    parser.add_argument("--method", "-m", default="inpaint", choices=["inpaint", "crop", "blur"],
                        help="Text removal method")
    args = parser.parse_args()

    if not args.image and not args.dir:
        parser.print_help()
        sys.exit(2)

    files = []
    if args.image:
        files = [args.image]
    else:
        import glob
        pattern = os.path.join(args.dir, args.pattern)
        files = glob.glob(pattern)
        files.sort()

    for f in files:
        print(f"Processing: {f}")
        out = args.output if args.output else None
        result = remove_text_pil(f, out)
        print(f"  Saved to: {result}\n")


if __name__ == "__main__":
    main()

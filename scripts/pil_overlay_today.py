#!/usr/bin/env python3
"""PIL overlay script for V4 cover generation:叠加主标题到底图上"""
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONTS = [
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
]

def find_font(size):
    for fp in FONTS:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except:
                continue
    return ImageFont.load_default()

def add_title_overlay(bg_path, output_path, title, is_cover=True):
    """Add title overlay to background image."""
    img = Image.open(bg_path)
    draw = ImageDraw.Draw(img)
    w, h = img.size

    max_chars_per_line = 12 if is_cover else 8
    lines = []
    remaining = title
    while remaining:
        if len(remaining) <= max_chars_per_line:
            lines.append(remaining)
            remaining = ""
        else:
            chunk = remaining[:max_chars_per_line]
            lines.append(chunk)
            remaining = remaining[max_chars_per_line:]

    if is_cover:
        font_size = min(72, int(720 / (len(lines) * 1.8)))
    else:
        font_size = min(52, int(1024 / (len(lines) * 2.2)))

    font = find_font(font_size)

    line_spacing = font_size * 0.4
    total_height = len(lines) * font_size + (len(lines) - 1) * line_spacing
    start_y = (h - total_height) // 2
    stroke = max(3, font_size // 12)

    for i, line in enumerate(lines):
        y = start_y + i * (font_size + line_spacing)
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (w - text_w) // 2
        draw.text((x, y), line, font=font, fill="black", stroke_width=stroke, stroke_fill="black")
        draw.text((x, y), line, font=font, fill="white", stroke_width=stroke, stroke_fill="black")

    img.save(output_path, "PNG")
    print(f"  Saved overlay: {output_path} ({w}x{h})")

# ---- Main ----
IMG_DIR = Path("D:/opc/ready-to-publish/2026-05-26/imgs")

# Article 1: 学考补考
title1 = "学考补考最后5天"
add_title_overlay(
    IMG_DIR / "WeChat_official_account_cover__2026-05-26T10-34-02.png",
    IMG_DIR / "xuekao-bukao-registration_cover.png",
    title1,
    is_cover=True
)
add_title_overlay(
    IMG_DIR / "Square_social_media_thumbnail__2026-05-26T10-35-33.png",
    IMG_DIR / "xuekao-bukao-registration_sub.png",
    title1,
    is_cover=False
)

# Article 2: 足球特色班
title2 = "足球特色班零分避坑"
add_title_overlay(
    IMG_DIR / "WeChat_official_account_cover__2026-05-26T10-34-49.png",
    IMG_DIR / "football-special-class-scoring_cover.png",
    title2,
    is_cover=True
)
add_title_overlay(
    IMG_DIR / "Square_social_media_thumbnail__2026-05-26T10-35-43.png",
    IMG_DIR / "football-special-class-scoring_sub.png",
    title2,
    is_cover=False
)

print("\nAll 4 overlays done!")

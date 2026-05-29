"""
OCR extract text from downloaded images of 划片范围 tables.
"""
import os
import re
import glob
from PIL import Image
import pytesseract

IMAGES_DIR = r"D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_初中划片\ocr_images"
OUTPUT_DIR = r"D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_初中划片"

DISTRICTS = ["武侯区", "高新区", "双流区", "郫都区"]  # 龙泉驿区 no images

def ocr_image(image_path):
    """OCR a single image with Chinese language support."""
    try:
        img = Image.open(image_path)
        # Preprocess: convert to grayscale and increase contrast
        img = img.convert('L')
        # Try OCR with Chinese
        text = pytesseract.image_to_string(img, lang='chi_sim+eng', config='--psm 6')
        return text
    except Exception as e:
        return f"ERROR: {e}"

def main():
    for district in DISTRICTS:
        print(f"\n{'='*60}")
        print(f"OCR for {district}...")
        
        # Find all images for this district
        pattern = os.path.join(IMAGES_DIR, f"{district}_wechat_*.png")
        png_files = sorted(glob.glob(pattern))
        pattern_jpg = os.path.join(IMAGES_DIR, f"{district}_wechat_*.jpg")
        jpg_files = sorted(glob.glob(pattern_jpg))
        all_files = sorted(png_files + jpg_files)
        
        print(f"  Found {len(all_files)} images")
        
        all_text = []
        for img_path in all_files:
            filename = os.path.basename(img_path)
            print(f"  OCR: {filename}...", end=" ", flush=True)
            text = ocr_image(img_path)
            size = os.path.getsize(img_path)
            
            # Only keep meaningful text (filter out tiny images like logos/icons)
            if len(text.strip()) > 20:
                all_text.append(f"--- {filename} ---\n{text}")
                print(f"✓ ({len(text)} chars)")
            else:
                print(f"skip (too short: {repr(text.strip()[:50])})")
        
        # Save combined OCR text
        if all_text:
            output_file = os.path.join(OUTPUT_DIR, f"2025_{district}_初中划片_ocr.txt")
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(f"区县: {district}\n")
                f.write(f"级别: 初中划片\n")
                f.write(f"来源: 微信公众号OCR提取\n")
                f.write(f"注意: OCR可能存在识别错误，请以官方原文为准\n")
                f.write("=" * 60 + "\n\n")
                f.write("\n\n".join(all_text))
            print(f"  ✓ Saved to {output_file}")
        else:
            print(f"  ✗ No meaningful text extracted")

if __name__ == "__main__":
    main()

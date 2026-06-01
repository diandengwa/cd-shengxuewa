#!/usr/bin/env python3
"""
Fix garbled text in Hunyuan-generated cover images.

Strategy V2:
1. OCR the image to find all text blocks (with bbox coordinates)
2. Identify the main title (largest bbox area, has Chinese)
3. Detect symmetric pairs (left/right matching blocks)
4. For garbled/non-main-title blocks:
   - Use OpenCV Inpainting (texture-aware fill) instead of solid rectangle
   - If symmetric pair exists, process both sides consistently
5. Final OCR check

Usage:
    python fix_cover_garble.py <image_path> [--output <path>] [--dry-run]
    python fix_cover_garble.py --dir <dir> [--pattern "*.png"]
"""

import argparse
import json
import os
import sys
import re
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import cv2

# ---- OCR (reuse cover_validator logic) ----

def get_reader():
    import easyocr
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    return easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)

def ocr_with_bbox(image_path: str):
    """Run OCR and return list of (bbox, text, conf)."""
    from PIL import Image as PILImage
    reader = get_reader()
    img = PILImage.open(image_path).convert('RGB')
    img_np = np.array(img)
    result = reader.readtext(img_np, detail=1)
    return result  # list of (bbox, text, conf)

# ---- Garble detection (from cover_validator.py) ----

COMMON_CHARS = set(
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取完举色或找付信修保推采望构摸检确座摄疑潮熟奖版独玛环畅略盖盛盘移税穿系久低假像偶偷偿催允元充兆先光入全八公六共关兴兵其具典写军农况冷准刀刊列则创初删利刷剧剩劳势匠匹占卡卫印危卵卷厚原厕去参又叉及友双反发取受变Ancient口古句另只叫可台史叶号吃各合同名后向吗否吧启告员味命和品哈响哪商啊喜喝喂嘛器回因园国图圆圣在地块坏坐块坚坛坟坠坤坦型城基堂堆堡塔填境墙墨士壮声壳备复外多夜够大天太央失头奖女她好如妇妈姐姓委姿娘婚婆婚嫂嫁嫌子字存孙学孩实客室家容宽察寨寸对寻导寿封将尊少尔尘尝就尺尼尽尾层居屋屏展属山岩岸川州工左巧己已巴巷巾市布师帝带常幅干平年并广庄庆床库应底店庙府庞废建弄式弟张弥弱弹强当录形彩影径很律得循心必忆志忘忠念怕思总息恶悉悬悲情想法皇监盖盘盛省着知短石破示礼社神秀私种科秒租积称移程穷穿窗立竖章童笔等第筒算管类粉粘精索约级线组结给绝统继续维网置罚美群老考者耐耳耻联胃背能脑脸自至舞航般色艺节芒苏苦英苹茶药菜营落著藏虑虽补袭装裤见观规视觉解言警计认讨让议记许论设证识诉诊词试诗话该说请课谁调谈谋谎象贝贡财责败货质贴费资赏赖趣足跑跟路跳身车轨转轮软轻载轿较达过迎运近还这进远连述迷追退送适逃选遗遥那部都酒里重野量金针钟铁银错长门闪闭问间队阳阴阵阶阿附陆降限院除陪隐难雄雨雪需露青静非面音项顺须顾领风飞饭饮馆首马骂高鬼鲜鹿麦黄黑"
)

def is_garbled(text: str, conf: float) -> dict:
    result = {"text": text, "conf": conf, "is_garbled": False, "reason": ""}
    if '\ufffd' in text or '�' in text:
        result["is_garbled"] = True
        result["reason"] = "contains replacement character"
        return result

    chinese_chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
    has_chinese = len(chinese_chars) > 0

    # Rule: skip watermark
    if "生成" in text and conf < 0.3:
        return result
    if "图片" in text and conf < 0.3:
        return result

    # Rule: nonsense uppercase
    upper_words = [w for w in text.split() if w.isalpha() and w.isupper() and len(w) >= 4]
    if upper_words:
        COMMON_EN = {'TITLE','GUIDE','TIPS','NEWS','UPDATE','REPORT','ANALYSIS',
                      'SCHOOL','EDUCATION','KINDERGARTEN','ADMISSION','ENROLL',
                      'DEADLINE','CONFIRM','STATUS','RESULT','POLICY','RULE',
                      'CHINA','BEIJING','SHANGHAI','SHENZHEN','CHENGDU',
                      'PRIMARY','MIDDLE','HIGH','COLLEGE','UNIVERSITY',
                      'AI','GPT','API','APP','WEB','HTML','CSS',
                      'COVER','IMAGE','PICTURE','PHOTO','GRAPHIC','DESIGN',
                      'TIME','DATE','YEAR','MONTH','DAY',
                      'NEW','HOT','TOP','BEST','FREE','PRO',
                      'INFO','PDF','DOC','ZIP','MP4','JPG','PNG'}
        has_common = any(w in COMMON_EN for w in upper_words)
        def is_random(w):
            vowels = set('AEIOU')
            return not any(c in vowels for c in w) and len(w) >= 5
        random_words = [w for w in upper_words if is_random(w)]
        if random_words and not has_common:
            result["is_garbled"] = True
            result["reason"] = f"nonsense uppercase: {random_words[0]!r}"
            return result

    # Rule: rare Chinese chars
    if has_chinese and len(chinese_chars) >= 2:
        uncommon = [c for c in chinese_chars if c not in COMMON_CHARS]
        rare_ratio = len(uncommon) / len(chinese_chars)
        if rare_ratio <= 0.3 and len(chinese_chars) >= 4:
            return result
        if rare_ratio > 0.5 and conf < 0.5:
            result["is_garbled"] = True
            result["reason"] = f"{rare_ratio:.0%} rare chars (conf={conf:.2f})"
            return result

    if conf < 0.15 and len(text) >= 3:
        result["is_garbled"] = True
        result["reason"] = f"conf too low ({conf:.2f})"
        return result

    return result

# ---- Geometry helpers ----

def bbox_to_rect(bbox):
    """Convert 4-corner bbox to (left, top, right, bottom, cx, cy, width, height)."""
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    left, right = int(min(xs)), int(max(xs))
    top, bottom = int(min(ys)), int(max(ys))
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    return left, top, right, bottom, cx, cy, right - left, bottom - top

def bbox_iou(bbox1, bbox2):
    """Compute IoU of two bboxes."""
    l1, t1, r1, b1, _, _, _, _ = bbox_to_rect(bbox1)
    l2, t2, r2, b2, _, _, _, _ = bbox_to_rect(bbox2)
    il = max(l1, l2)
    it = max(t1, t2)
    ir = min(r1, r2)
    ib = min(b1, b2)
    if ir <= il or ib <= it:
        return 0.0
    inter = (ir - il) * (ib - it)
    area1 = (r1 - l1) * (b1 - t1)
    area2 = (r2 - l2) * (b2 - t2)
    return inter / (area1 + area2 - inter + 1e-6)

# ---- Main title detection ----

def find_main_title(ocr_results):
    """
    Identify the primary main title block.
    Heuristic: LARGEST bbox area with Chinese chars (ignore conf).
    Returns index, or None.
    """
    best_idx = None
    best_area = 0
    for idx, r in enumerate(ocr_results):
        bbox, text, conf = r
        chinese_chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
        if not chinese_chars:
            continue
        _, _, _, _, _, _, w, h = bbox_to_rect(bbox)
        area = w * h
        if area > best_area:
            best_area = area
            best_idx = idx
    return best_idx

def find_main_title_blocks(ocr_results):
    """
    Identify ALL blocks that belong to the main title area.
    Returns set of indices to skip.
    """
    primary_idx = find_main_title(ocr_results)
    if primary_idx is None:
        return set()

    skip = {primary_idx}
    _, _, _, _, _, _, _, h_primary = bbox_to_rect(ocr_results[primary_idx][0])
    cy_primary = bbox_to_rect(ocr_results[primary_idx][0])[5]

    for idx, r in enumerate(ocr_results):
        if idx == primary_idx:
            continue
        bbox = r[0]
        _, _, _, _, _, cy, _, h = bbox_to_rect(bbox)
        # Same title row: y-center within 60% of primary title height
        if abs(cy - cy_primary) < max(h_primary * 0.6, 50):
            skip.add(idx)

    return skip

# ---- Symmetry detection ----

def detect_symmetric_pairs(ocr_results, img_width):
    """
    Detect pairs of blocks that appear symmetric around image center.
    Returns dict: index -> partner_index (or None if no partner).
    """
    center_x = img_width / 2.0
    pairs = {}
    used = set()

    for i, r1 in enumerate(ocr_results):
        if i in used:
            continue
        _, _, _, _, cx1, cy1, w1, h1 = bbox_to_rect(r1[0])
        # Only consider blocks that are clearly on one side
        if abs(cx1 - center_x) < img_width * 0.15:
            continue  # Too close to center

        best_match = None
        best_score = float('inf')

        for j, r2 in enumerate(ocr_results):
            if i == j or j in used:
                continue
            _, _, _, _, cx2, cy2, w2, h2 = bbox_to_rect(r2[0])
            # Must be on opposite side
            if (cx1 < center_x and cx2 < center_x) or (cx1 > center_x and cx2 > center_x):
                continue
            # Check horizontal symmetry
            mirror_x = center_x - (cx1 - center_x)
            x_diff = abs(cx2 - mirror_x)
            # Check vertical alignment
            y_diff = abs(cy1 - cy2)
            # Check size similarity
            size_diff = abs(w1 - w2) + abs(h1 - h2)

            score = x_diff + y_diff * 2 + size_diff * 0.5
            if x_diff < img_width * 0.25 and y_diff < max(h1, h2) * 1.2 and score < best_score:
                best_score = score
                best_match = j

        if best_match is not None:
            pairs[i] = best_match
            pairs[best_match] = i
            used.add(i)
            used.add(best_match)

    return pairs

# ---- Inpainting fix ----

def fix_with_inpaint(img_np, bbox, expand=6):
    """
    Use OpenCV Inpainting to remove text at bbox.
    Returns modified img_np.
    """
    h, w = img_np.shape[:2]
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    left = max(0, int(min(xs)) - expand)
    top = max(0, int(min(ys)) - expand)
    right = min(w, int(max(xs)) + expand)
    bottom = min(h, int(max(ys)) + expand)

    # Create mask: text area = 255, rest = 0
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[top:bottom, left:right] = 255

    # Dilate mask slightly to cover text edges
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)

    # Inpaint using both algorithms and blend
    result_ns = cv2.inpaint(img_np, mask, inpaintRadius=3, flags=cv2.INPAINT_NS)
    result_telea = cv2.inpaint(img_np, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

    # Blend: Telea for structure, NS for texture
    result = cv2.addWeighted(result_telea, 0.6, result_ns, 0.4, 0)

    return result

def fix_with_blur_fallback(img_np, bbox, expand=10):
    """
    Fallback: Gaussian blur the text area to blend with surroundings.
    Used when inpainting leaves artifacts.
    """
    h, w = img_np.shape[:2]
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    left = max(0, int(min(xs)) - expand)
    top = max(0, int(min(ys)) - expand)
    right = min(w, int(max(xs)) + expand)
    bottom = min(h, int(max(ys)) + expand)

    roi = img_np[top:bottom, left:right]
    if roi.size == 0:
        return img_np

    # Progressive blur
    blurred = cv2.GaussianBlur(roi, (25, 25), 0)
    blurred = cv2.GaussianBlur(blurred, (15, 15), 0)

    # Feathered blend: center fully blurred, edges preserve original
    fh, fw = blurred.shape[:2]
    if fh > 10 and fw > 10:
        feather = np.zeros((fh, fw), dtype=np.float32)
        margin = min(fh, fw) // 4
        feather[margin:fh-margin, margin:fw-margin] = 1.0
        feather = cv2.GaussianBlur(feather, (margin*2+1, margin*2+1), 0)
        feather_3ch = np.stack([feather]*3, axis=2)
        blended = (blurred.astype(np.float32) * feather_3ch +
                   roi.astype(np.float32) * (1 - feather_3ch)).astype(np.uint8)
    else:
        blended = blurred

    img_np[top:bottom, left:right] = blended
    return img_np

# ---- Main fix logic ----

def fix_image(image_path: str, output_path: str = None, dry_run: bool = False):
    """Fix garbled text in a cover image."""
    if not os.path.exists(image_path):
        print(f"ERROR: file not found: {image_path}")
        return False

    print(f"\n{'='*60}")
    print(f"Fixing: {image_path}")
    print(f"{'='*60}")

    # Step 1: OCR
    print("[1/5] Running OCR...")
    ocr_results = ocr_with_bbox(image_path)
    print(f"  Found {len(ocr_results)} text block(s)")

    if not ocr_results:
        print("  No text blocks found. Image may already be text-free.")
        if output_path:
            import shutil
            shutil.copy(image_path, output_path)
            print(f"  Copied to {output_path}")
        return True

    # Step 2: Find main title blocks
    print("[2/5] Identifying main title area...")
    skip_indices = find_main_title_blocks(ocr_results)
    if skip_indices:
        for idx in sorted(skip_indices):
            mt = ocr_results[idx]
            print(f"  Main title area: {mt[1]!r} (conf={mt[2]:.2f})")
    else:
        print("  No main title detected")

    # Step 3: Detect symmetric pairs
    print("[3/5] Detecting symmetric structure...")
    img = Image.open(image_path).convert('RGB')
    img_np = np.array(img)
    sym_pairs = detect_symmetric_pairs(ocr_results, img.width)
    if sym_pairs:
        paired = set()
        for i, j in sym_pairs.items():
            if i < j and i not in paired:
                print(f"  Symmetric pair: {ocr_results[i][1]!r} <-> {ocr_results[j][1]!r}")
                paired.add(i)
                paired.add(j)
    else:
        print("  No symmetric pairs detected")

    # Step 4: Identify blocks to fix
    print("[4/5] Identifying blocks to fix...")
    fix_blocks = []
    for idx, r in enumerate(ocr_results):
        bbox, text, conf = r
        is_skip = idx in skip_indices

        # In main title area: only fix if truly garbled or extremely low conf
        if is_skip:
            check = is_garbled(text, conf)
            if check["is_garbled"] or conf < 0.15:
                fix_blocks.append((idx, r, check["reason"] or f"title area conf={conf:.2f}"))
                print(f"  FIX (title area): {text!r} conf={conf:.2f}")
            else:
                print(f"  SKIP (main title): {text!r} conf={conf:.2f}")
            continue

        check = is_garbled(text, conf)
        if check["is_garbled"]:
            fix_blocks.append((idx, r, check["reason"]))
            print(f"  FIX (garbled): {text!r} conf={conf:.2f} → {check['reason']}")
        elif conf < 0.3:
            fix_blocks.append((idx, r, "low confidence"))
            print(f"  FIX (low conf): {text!r} conf={conf:.2f}")
        else:
            print(f"  KEEP: {text!r} conf={conf:.2f}")

    if not fix_blocks:
        print("\n  ✅ No garbled blocks found! Image is clean.")
        if output_path:
            import shutil
            shutil.copy(image_path, output_path)
            print(f"  Copied to {output_path}")
        return True

    # Step 5: Apply fixes with symmetry consistency
    print(f"\n[5/5] Fixing {len(fix_blocks)} block(s)...")

    # Track which indices we're fixing
    fix_indices = {idx for idx, _, _ in fix_blocks}

    # Handle symmetric consistency: if one side of a pair is fixed, fix the other too
    for idx, r, reason in list(fix_blocks):
        if idx in sym_pairs:
            partner = sym_pairs[idx]
            if partner not in fix_indices and partner not in skip_indices:
                # Partner is not garbled but for visual symmetry, remove it too
                # (unless it's main title)
                print(f"  SYMMETRY: Also removing {ocr_results[partner][1]!r} to match fixed side")
                fix_blocks.append((partner, ocr_results[partner], "symmetry"))
                fix_indices.add(partner)

    for idx, r, reason in fix_blocks:
        bbox, text, conf = r
        print(f"  Processing: {text!r} (reason: {reason})")

        # Try inpainting first
        img_np = fix_with_inpaint(img_np, bbox, expand=6)

        # Fallback: check if inpainting left artifacts by looking at variance
        left, top, right, bottom, _, _, _, _ = bbox_to_rect(bbox)
        left = max(0, left - 6)
        top = max(0, top - 6)
        right = min(img_np.shape[1], right + 6)
        bottom = min(img_np.shape[0], bottom + 6)

        roi = img_np[top:bottom, left:right]
        if roi.size > 0:
            gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
            variance = cv2.Laplacian(gray, cv2.CV_64F).var()
            # If variance is too low (flat color), use blur fallback for better blending
            if variance < 50:
                print(f"    -> Inpainting too flat, applying blur fallback")
                img_np = fix_with_blur_fallback(img_np, bbox, expand=10)

    if dry_run:
        print("\n  [DRY RUN] No changes saved.")
        return True

    # Save
    if output_path is None:
        base, ext = os.path.splitext(image_path)
        output_path = f"{base}_fixed{ext}"

    result_img = Image.fromarray(img_np)
    result_img.save(output_path, quality=95)
    print(f"\n  ✅ Saved fixed image: {output_path}")

    # Final OCR check
    print("\n  Running final OCR check...")
    ocr_results2 = ocr_with_bbox(output_path)
    garbled_count = 0
    for r in ocr_results2:
        text, conf = r[1], r[2]
        check = is_garbled(text, conf)
        if check["is_garbled"]:
            garbled_count += 1
            print(f"  ⚠️  Still garbled: {text!r} ({check['reason']})")

    if garbled_count == 0:
        print("  ✅ Final check passed! No garbled text remaining.")
    else:
        print(f"  ⚠️  {garbled_count} garbled block(s) still remain.")

    return True

def main():
    parser = argparse.ArgumentParser(description="Fix garbled text in cover images")
    parser.add_argument("--image", "-i", help="Path to single image")
    parser.add_argument("--dir", "-d", help="Directory to scan")
    parser.add_argument("--pattern", "-p", default="*.png", help="Glob pattern")
    parser.add_argument("--output", "-o", help="Output path (single image mode)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fixed, don't save")
    parser.add_argument("--json", "-j", action="store_true", help="Output results as JSON")
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
        files = sorted(glob.glob(pattern))

    results = []
    for f in files:
        ok = fix_image(f, args.output if args.image else None, dry_run=args.dry_run)
        results.append({"file": f, "fixed": ok})

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

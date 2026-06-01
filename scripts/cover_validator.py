#!/usr/bin/env python3
"""
Cover Image Quality Validator

Uses OCR (easyocr) to detect Chinese garbled text in AI-generated cover images.

Usage:
    python cover_validator.py --image <path> [--threshold 0.35] [--verbose]
    python cover_validator.py --dir <dir> [--pattern "*.png"] [--threshold 0.35]

Exit code:
    0 = pass (no garbled text detected)
    1 = fail (garbled text detected)
    2 = error (file not found, OCR failure, etc.)
"""

import argparse
import glob
import json
import os
import sys

# Lazy-load easyocr to avoid heavy import when just checking args
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        import numpy as np
        # Suppress torch warnings
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)
        _reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
        # Attach np for later use
        _reader._np = np
    return _reader


# Common Chinese characters (simplified, ~3500 most frequent)
# Used to detect garbled text: if a Chinese text block has too many
# characters outside this set, it's likely garbled.
COMMON_CHARS = set(
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取完举色或找付信修保推采望构摸检确座摄疑潮熟奖版独玛环畅略盖盛盘移税穿系久低假像偶偷偿催允元充兆先光入全八公六共关兴兵其具典写军农况冷准刀刊列则创初删利刷剧剩劳势匠匹占卡卫印危卵卷厚原厕去参又叉及友双反发取受变 Ancient口古句另只叫可台史叶号吃各合同名后向吗否吧启告员味命和品哈响哪商啊喜喝喂嘛器回因园国图圆圣在地块坏坐块坚坛坟坠坤坦型城基堂堆堡塔填境墙墨士壮声壳备复外多夜够大天太央失头奖女她好如妇妈姐姓委姿娘婚婆婚嫂嫁嫌子字存孙学孩实客室家容宽察寨寸对寻导寿封将尊少尔尘尝就尺尼尽尾层居屋屏展属山岩岸川州工左巧己已巴巷巾市布师帝带常幅干平年并广庄庆床库应底店庙府庞废建弄式弟张弥弱弹强当录形彩影径很律得循心必忆志忘忠念怕思总息恶悉悬悲情想法皇监盖盘盛省着知短石破示礼社神秀私种科秒租积称移程穷穿窗立竖章童笔等第筒算管类粉粘精索约级线组结给绝统继续维网置罚美群老考者耐耳耻联胃背能脑脸自至舞航般色艺节芒苏苦英苹茶药菜营落著藏虑虽补袭装裤见观规视觉解言警计认讨让议记许论设证识诉诊词试诗话该说请课谁调谈谋谎象贝贡财责败货质贴费资赏赖趣足跑跟路跳身车轨转轮软轻载轿较达过迎运近还这进远连述迷追退送适逃选遗遥那部都酒里重野量金针钟铁银错长门闪闭问间队阳阴阵阶阿附陆降限院除陪隐难雄雨雪需露青静非面音项顺须顾领风飞饭饮馆首马骂高鬼鲜鹿麦黄黑"
)

def is_garbled_chinese(text: str, conf: float) -> dict:
    """
    Analyze a single OCR text block for garbled Chinese text.
    Returns a dict with verdict and reason.
    """
    result = {
        "text": text,
        "conf": conf,
        "is_garbled": False,
        "reason": ""
    }

    # Rule 1: Contains replacement character or obvious corruption markers
    if '\ufffd' in text or '�' in text:
        result["is_garbled"] = True
        result["reason"] = "contains replacement character"
        return result

    # Extract Chinese characters for analysis
    chinese_chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
    has_chinese = len(chinese_chars) > 0

    # Rule 2: Ignore known watermarks / artifacts FIRST
    # Hunyuan-generated images have "图片由AI生成" watermark in bottom-right corner
    # OCR may misread it as "U41生成", "AI生成", "A1生成", etc.
    # Heuristic: if text contains "生成" and conf < 0.3, likely a watermark
    if "生成" in text and conf < 0.3:
        return result  # skip watermark, not garbled text
    # Also check for "图片" watermark variants
    if "图片" in text and conf < 0.3:
        return result

    # Rule 3: Detect nonsense English/roman letter sequences
    # e.g. "ITS ATICFTRCC" — all caps, no vowels or unpronounceable
    # Whitelist common English words used in cover designs
    COMMON_EN_WORDS = {
        'TITLE', 'GUIDE', 'TIPS', 'NEWS', 'UPDATE', 'REPORT', 'ANALYSIS',
        'SCHOOL', 'EDUCATION', 'KINDERGARTEN', 'ADMISSION', 'ENROLL', 'ENROLLMENT',
        'DEADLINE', 'CONFIRM', 'STATUS', 'RESULT', 'POLICY', 'RULE', 'RULES',
        'CHINA', 'BEIJING', 'SHANGHAI', 'SHENZHEN', 'CHENGDU', 'GUANGZHOU',
        'PRIMARY', 'MIDDLE', 'HIGH', 'COLLEGE', 'UNIVERSITY', 'CAMPUS',
        'AI', 'GPT', 'API', 'APP', 'WEB', 'HTML', 'CSS', 'URL',
        'COVER', 'IMAGE', 'PICTURE', 'PHOTO', 'GRAPHIC', 'DESIGN', 'LAYOUT',
        'TIME', 'DATE', 'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE',
        'NEW', 'HOT', 'TOP', 'BEST', 'FREE', 'PRO', 'MAX', 'MIN',
        'INFO', 'PDF', 'DOC', 'ZIP', 'MP4', 'JPG', 'PNG',
        'USA', 'UK', 'EU', 'UN', 'WHO', 'COVID', 'DNA', 'RNA',
        'MATH', 'SCIENCE', 'ART', 'MUSIC', 'SPORT', 'GAME', 'CODE',
        'WECHAT', 'TIKTOK', 'WHATSAPP', 'INSTA', 'YOUTUBE',
        'SUMMARY', 'ABSTRACT', 'INTRO', 'OUTLINE', 'CHAPTER', 'SECTION',
        'IMPORTANT', 'URGENT', 'WARNING', 'NOTICE', 'ALERT',
        'STEP', 'STEPS', 'HOW', 'WHAT', 'WHY', 'WHEN', 'WHERE',
        'KNOW', 'LEARN', 'STUDY', 'TEACH', 'TEST', 'EXAM', 'SCORE',
        'LIMITED', 'OFFER', 'SALE', 'PRICE', 'COST', 'FEE',
        'HORIZON', 'GLOW', 'RISE', 'HERO', 'EPIC', 'PRO', 'TOP',
        'WEEK', 'MONTH', 'YEAR', 'TODAY', 'TOMORROW', 'NOW', 'SOON',
        'WILL', 'CAN', 'MAY', 'MUST', 'SHOULD', 'NEED',
        'AD', 'BC', 'AM', 'PM', 'EST', 'PST', 'UTC', 'GMT',
        'PROFESSIONAL', 'PREMIUM', 'DELUXE', 'ULTRA', 'SUPER', 'MEGA',
        'STUDIO', 'LAB', 'WORKSHOP', 'SEMINAR', 'COURSE', 'CLASS',
        'AUTHOR', 'WRITER', 'EDITOR', 'REVIEWER', 'EXPERT', 'MASTER',
        'FINAL', 'DRAFT', 'VERSION', 'EDITION', 'VOLUME', 'ISSUE',
        'PAGE', 'PARAGRAPH', 'SENTENCE', 'WORD', 'LETTER', 'NUMBER',
        'FIRST', 'SECOND', 'THIRD', 'LAST', 'NEXT', 'PREVIOUS',
        'OPEN', 'CLOSE', 'START', 'END', 'BEGIN', 'FINISH', 'COMPLETE',
        'SUCCESS', 'FAIL', 'ERROR', 'WARNING', 'INFO', 'DEBUG',
        'VERSION', 'V1', 'V2', 'V3', 'BETA', 'ALPHA', 'RC',
        'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
    }
    upper_words = [w for w in text.split() if w.isalpha() and w.isupper() and len(w) >= 4]
    if upper_words:
        # Check if any word is a common English word
        has_common = any(w in COMMON_EN_WORDS for w in upper_words)
        # Check if it looks like random letters (no vowels or too many consonants)
        def is_random_word(w):
            vowels = set('AEIOU')
            has_vowel = any(c in vowels for c in w)
            # Allow if has vowel or is a known word
            return not has_vowel and len(w) >= 5
        random_words = [w for w in upper_words if is_random_word(w)]
        if random_words and not has_common:
            result["is_garbled"] = True
            result["reason"] = f"nonsense uppercase sequence: {random_words[0]!r}"
            return result

    # Rule 4: Chinese text analysis (primary focus)
    if has_chinese and len(chinese_chars) >= 2:
        uncommon = [c for c in chinese_chars if c not in COMMON_CHARS]
        rare_ratio = len(uncommon) / len(chinese_chars)

        # If most chars are common (>70%) and the text looks readable,
        # it's probably OK even with low OCR confidence
        if rare_ratio <= 0.3 and len(chinese_chars) >= 4:
            # Likely normal text; OCR confidence is just low due to artistic fonts
            return result

        # If many rare chars AND low confidence -> garbled
        if rare_ratio > 0.5 and conf < 0.5:
            result["is_garbled"] = True
            result["reason"] = f"{rare_ratio:.0%} rare Chinese chars (conf={conf:.2f})"
            return result

    # Rule 5: Very low confidence for non-Chinese or very short text
    if conf < 0.15 and len(text) >= 3:
        result["is_garbled"] = True
        result["reason"] = f"confidence too low ({conf:.2f} < 0.15)"
        return result

    return result


def validate_image(image_path: str, threshold: float = 0.35, verbose: bool = False) -> dict:
    """
    Validate a single image file.
    Returns result dict.
    """
    if not os.path.exists(image_path):
        return {
            "path": image_path,
            "status": "error",
            "error": "file not found",
            "garbled_blocks": [],
            "pass": False
        }

    try:
        from PIL import Image
        reader = get_reader()
        img = Image.open(image_path).convert('RGB')
        result = reader.readtext(reader._np.array(img), detail=1)
    except Exception as e:
        return {
            "path": image_path,
            "status": "error",
            "error": str(e),
            "garbled_blocks": [],
            "pass": False
        }

    garbled_blocks = []
    all_blocks = []

    for r in result:
        # r format: (bbox, text, conf)
        # bbox is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] - may contain numpy int32
        bbox_raw = r[0]
        bbox = [[int(c) for c in point] for point in bbox_raw]
        text = r[1].strip()
        conf = float(r[2])
        if not text:
            continue

        check = is_garbled_chinese(text, conf)
        block_info = {**check, "bbox": bbox}
        all_blocks.append(block_info)
        if check["is_garbled"]:
            garbled_blocks.append(block_info)

    passed = len(garbled_blocks) == 0

    res = {
        "path": image_path,
        "status": "ok",
        "pass": passed,
        "total_blocks": len(all_blocks),
        "garbled_count": len(garbled_blocks),
        "garbled_blocks": garbled_blocks,
        "all_blocks": all_blocks if verbose else None
    }

    return res


def main():
    parser = argparse.ArgumentParser(description="Validate cover image quality via OCR")
    parser.add_argument("--image", "-i", help="Path to single image file")
    parser.add_argument("--dir", "-d", help="Directory to scan for images")
    parser.add_argument("--pattern", "-p", default="*.png", help="Glob pattern for --dir (default: *.png)")
    parser.add_argument("--threshold", "-t", type=float, default=0.35, help="Confidence threshold (default: 0.35)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all OCR blocks")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if not args.image and not args.dir:
        parser.print_help()
        sys.exit(2)

    files = []
    if args.image:
        files = [args.image]
    else:
        pattern = os.path.join(args.dir, args.pattern)
        files = glob.glob(pattern)
        files.sort()

    results = []
    any_fail = False
    any_error = False

    for f in files:
        res = validate_image(f, threshold=args.threshold, verbose=args.verbose)
        results.append(res)
        if res.get("status") == "error":
            any_error = True
        elif not res.get("pass", True):
            any_fail = True

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for res in results:
            status_icon = "✅" if res.get("pass") else ("❌" if res.get("status") == "ok" else "⚠️")
            print(f"{status_icon} {res['path']}")
            if res.get("status") == "error":
                print(f"   ERROR: {res.get('error')}")
            elif not res.get("pass"):
                print(f"   Garbled text detected ({res['garbled_count']} block(s)):")
                for b in res["garbled_blocks"]:
                    print(f"     • {b['text']!r} (conf={b['conf']:.2f}) → {b['reason']}")
            if args.verbose and res.get("all_blocks"):
                print(f"   All detected text:")
                for b in res["all_blocks"]:
                    icon = "❌" if b["is_garbled"] else "  "
                    print(f"     {icon} {b['text']!r} (conf={b['conf']:.2f})")
            print()

    # Exit codes: 0=pass, 1=garbled detected, 2=error
    if any_error:
        sys.exit(2)
    if any_fail:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""opc-agent-knowledge migration script"""
import json
import shutil
from pathlib import Path
from datetime import datetime

OLD_KB = Path(r"D:\opc\knowledge-base")
NEW_KB = Path(r"D:\opc\opc-agent-knowledge")
WIKI_DIR = NEW_KB / "wiki" / "K12鍗囧"

def migrate_index():
    old_index = OLD_KB / "index.json"
    if not old_index.exists():
        print("Old index not found, skipping")
        return
    with open(old_index, "r", encoding="utf-8") as f:
        old_data = json.load(f)
    new_index = {
        "version": "2.0",
        "migrated_at": datetime.now().isoformat(),
        "source": "knowledge-base/ -> opc-agent-knowledge/",
        "categories": {},
        "domain": "K12鍗囧",
        "total_articles": 0
    }
    for cat, info in old_data.get("categories", {}).items():
        new_index["categories"][cat] = {
            "count": info.get("count", 0),
            "latest": info.get("latest", ""),
            "path": f"wiki/K12鍗囧/{cat}/"
        }
        new_index["total_articles"] += info.get("count", 0)
    output_path = WIKI_DIR / "_index.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(new_index, f, ensure_ascii=False, indent=2)
    print(f"Index migrated to {output_path}")
    return new_index

def migrate_category_files():
    categories = ["decision-frameworks", "fact-claims", "gap-analysis", "pain-points"]
    for cat in categories:
        old_cat_dir = OLD_KB / cat
        new_cat_dir = WIKI_DIR / cat
        new_cat_dir.mkdir(parents=True, exist_ok=True)
        if not old_cat_dir.exists():
            continue
        count = 0
        for old_file in old_cat_dir.glob("*.json"):
            new_file = new_cat_dir / old_file.name
            shutil.copy2(old_file, new_file)
            count += 1
        print(f"  {cat}: migrated {count} files")

def main():
    print("=== opc-agent-knowledge migration ===")
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    migrate_index()
    migrate_category_files()
    print("Migration complete.")

if __name__ == "__main__":
    main()


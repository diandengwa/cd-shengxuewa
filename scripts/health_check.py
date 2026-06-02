#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OPC Health Check Script
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_config

def check_directories(config) -> bool:
    """Check required directories"""
    required_dirs = [
        config.knowledge_base_dir,
        config.drafts_dir,
        config.reviewed_dir,
        config.ready_to_publish_dir,
        config.raw_articles_dir,
        config.logs_dir,
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        if not dir_path.exists():
            print(f"[WARN] Directory missing: {dir_path}")
            all_exist = False
        else:
            print(f"[OK] Directory exists: {dir_path}")
    
    return all_exist

def check_knowledge_base(config) -> bool:
    """Check knowledge base — supports both flat and nested layouts"""
    try:
        kb_dir = config.knowledge_base_dir
        if not kb_dir.exists():
            print(f"[WARN] Knowledge base directory missing: {kb_dir}")
            return False
        
        # Count knowledge cards (flat + nested)
        card_count = 0
        # 1) Flat: .json files directly in kb_dir
        flat_cards = list(kb_dir.glob('*.json'))
        card_count += len(flat_cards)
        # 2) Nested: .json files in sub-directories
        for cat_dir in kb_dir.iterdir():
            if cat_dir.is_dir() and not cat_dir.name.startswith('.'):
                card_count += len(list(cat_dir.glob('*.json')))
        
        print(f"[INFO] Knowledge cards: {card_count} (flat={len(flat_cards)})")
        return card_count > 0
    except Exception as e:
        print(f"[ERROR] Knowledge base check failed: {e}")
        return False

def main():
    print("=== OPC Health Check ===")
    print(f"Time: {datetime.now().isoformat()}")
    print()
    
    # Get config
    config = get_config()
    
    checks = {}
    
    # 1. Check directories
    print("1. Checking directories...")
    checks["directories"] = check_directories(config)
    print()
    
    # 2. Check knowledge base
    print("2. Checking knowledge base...")
    checks["knowledge_base"] = check_knowledge_base(config)
    print()
    
    # Generate report
    report = {
        "timestamp": datetime.now().isoformat(),
        "status": "healthy" if all(checks.values()) else "unhealthy",
        "checks": checks,
    }
    
    # Save report
    report_file = config.logs_dir / "health_report.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # Output results
    print("=== Results ===")
    for check, result in checks.items():
        status = "OK" if result else "FAIL"
        print(f"[{status}] {check}")
    
    print()
    print(f"Status: {'HEALTHY' if report['status'] == 'healthy' else 'UNHEALTHY'}")
    print(f"Report saved: {report_file}")
    
    return 0 if report['status'] == 'healthy' else 1

if __name__ == '__main__':
    sys.exit(main())

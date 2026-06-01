#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试配置加载器
"""

import sys
import os
from pathlib import Path

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import get_config

def main():
    # 获取配置
    config = get_config()
    
    print("=== OPC 配置测试 ===")
    print(f"OPC Root: {config.opc_root}")
    print(f"Knowledge Base: {config.knowledge_base_dir}")
    print(f"Drafts: {config.drafts_dir}")
    print(f"DeepSeek Key: {'*' * 10 if config.deepseek_api_key else '未设置'}")
    print(f"Min Score: {config.min_score}")
    print(f"Max Attempts: {config.max_attempts}")
    print(f"Default Count: {config.default_count}")
    print(f"Channels: {config.channels}")
    print(f"Forbidden Suffixes: {config.forbidden_suffixes}")
    print(f"Static Keywords: {config.static_keywords}")
    print(f"AI Smell Keywords: {config.ai_smell_keywords}")
    print(f"Xiaoshengchu Ratio: {config.xiaoshengchu_ratio}")
    print(f"Min Word Count: {config.min_word_count}")
    print(f"Max Word Count: {config.max_word_count}")
    print(f"Title Min Length: {config.title_min_length}")
    print(f"Title Max Length: {config.title_max_length}")

if __name__ == '__main__':
    main()

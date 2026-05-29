#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Copy raw 划片 data to Wiki datasets directory with proper naming."""

import shutil
from pathlib import Path

WIKI_DATASETS = Path(r'D:\cdopenclawqun\k12_ai_revival_20260429\wiki\datasets')
RAW_XIAOXUE = Path(r'D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片')
RAW_CHUZHONG = Path(r'D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_初中划片')

def copy_to_datasets(raw_dir, level_label):
    """Copy MD files from raw to datasets with wiki-standard naming."""
    count = 0
    for f in sorted(raw_dir.glob('2025_*.md')):
        # Target name: 2025_XX区_小学划片.md (same as raw)
        target = WIKI_DATASETS / f.name
        shutil.copy2(f, target)
        count += 1
        print(f'  ✅ {f.name}')
    return count

print('=== 复制划片数据到Wiki datasets ===\n')

print('## 小学划片')
xx_count = copy_to_datasets(RAW_XIAOXUE, '小学')
print(f'  共 {xx_count} 个文件\n')

print('## 初中划片')
cz_count = copy_to_datasets(RAW_CHUZHONG, '初中')
print(f'  共 {cz_count} 个文件\n')

print(f'总计: {xx_count + cz_count} 个文件已复制到 datasets/')

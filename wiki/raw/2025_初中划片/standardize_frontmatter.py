#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Standardize frontmatter for all 2025 初中划片 MD files."""

import re
from pathlib import Path

RAW_DIR = Path(r'D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_初中划片')

def main():
    updated = 0
    for f in sorted(RAW_DIR.glob('2025_*.md')):
        content = f.read_text(encoding='utf-8')
        
        if 'year:' in content[:200] and 'district:' in content[:200] and 'level:' in content[:200]:
            print(f'  skip {f.name} - already standard')
            continue
        
        match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if not match:
            print(f'  WARN {f.name}: no frontmatter')
            continue
        
        fm_text = match.group(1)
        fm = {}
        for line in fm_text.split('\n'):
            if ':' in line:
                key, val = line.split(':', 1)
                fm[key.strip()] = val.strip().strip('"').strip("'")
        
        body = content[match.end():]
        
        district = fm.get('district', f.stem.split('_')[1])
        source = fm.get('source', '网络抓取')
        trust = fm.get('trust_level', 'B')
        if '官方' in source or '教育局' in source:
            trust = 'S'
        elif '图片' in content[:500] or '无法提取' in content[:500]:
            trust = 'C'
        
        scraped = fm.get('archive_date', fm.get('scraped_at', '2026-04-30'))
        
        lines = ['---']
        lines.append('year: 2025')
        lines.append(f'district: {district}')
        lines.append('level: 初中')
        lines.append(f'source: "{source}"')
        lines.append(f'trust_level: "{trust}"')
        lines.append(f'scraped_at: "{scraped}"')
        lines.append('---')
        new_fm = '\n'.join(lines)
        
        new_content = new_fm + '\n' + body.lstrip('\n')
        f.write_text(new_content, encoding='utf-8')
        print(f'  OK {f.name}')
        updated += 1
    
    print(f'\nDone: {updated} files updated')

if __name__ == '__main__':
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Standardize frontmatter for all 2025 小学划片 MD files."""

import re
from pathlib import Path

RAW_DIR = Path(r'D:\cdopenclawqun\k12_ai_revival_20260429\wiki\raw\2025_小学划片')

STANDARD_FRONTMATTER_FIELDS = ['year', 'district', 'level', 'source', 'trust_level', 'scraped_at']

def extract_frontmatter(content):
    """Extract YAML frontmatter from markdown content."""
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}, content
    fm_text = match.group(1)
    fm = {}
    for line in fm_text.split('\n'):
        if ':' in line:
            key, val = line.split(':', 1)
            fm[key.strip()] = val.strip().strip('"').strip("'")
    body = content[match.end():]
    return fm, body

def build_standard_frontmatter(fm):
    """Build standardized frontmatter."""
    lines = ['---']
    lines.append(f'year: {fm.get("year", fm.get("policy_year", 2025))}')
    lines.append(f'district: {fm.get("district", "")}')
    lines.append(f'level: 小学')
    source = fm.get('source', '成都市教育局')
    lines.append(f'source: "{source}"')
    trust = fm.get('trust_level', 'S' if '官方' in source or '教育局' in source else 'B')
    lines.append(f'trust_level: "{trust}"')
    scraped = fm.get('scraped_at', fm.get('archive_date', fm.get('converted_at', '2026-04-30')))
    lines.append(f'scraped_at: "{scraped}"')
    # Preserve URL if exists
    if 'url' in fm:
        lines.append(f'url: "{fm["url"]}"')
    lines.append('---')
    return '\n'.join(lines)

def main():
    md_files = sorted(RAW_DIR.glob('2025_*.md'))
    print(f"Found {len(md_files)} MD files\n")

    updated = 0
    for f in md_files:
        content = f.read_text(encoding='utf-8')
        fm, body = extract_frontmatter(content)
        
        # Skip if already standardized format (has year, district, level fields)
        if 'year' in fm and 'district' in fm and 'level' in fm:
            # Already standard, just update trust_level if missing
            if 'trust_level' not in fm:
                source = fm.get('source', '')
                trust = 'S' if '官方' in source or '教育局' in source else 'B'
                fm['trust_level'] = trust
            else:
                print(f"  ⏭️ {f.name} - already standard")
                continue
        
        new_fm = build_standard_frontmatter(fm)
        new_content = new_fm + '\n' + body.lstrip('\n')
        f.write_text(new_content, encoding='utf-8')
        print(f"  ✅ {f.name}")
        updated += 1

    print(f"\nUpdated: {updated}")

if __name__ == '__main__':
    main()

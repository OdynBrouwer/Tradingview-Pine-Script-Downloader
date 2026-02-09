#!/usr/bin/env python3
"""Remove URLs listed in analyze/jsons/removed-fast-urls.txt from pinescript_downloads page-*.json files.
Backs up modified files under pinescript_downloads/backups/<timestamp>/...
Writes summary to analyze/jsons/pruned-pages-summary.json
"""
from pathlib import Path
import json, datetime, shutil

ROOT = Path('.').resolve()
DATA_DIR = ROOT / 'pinescript_downloads'
REMOVED_URLS_FILE = ROOT / 'analyze' / 'jsons' / 'removed-fast-urls.txt'
BACKUP_DIR = DATA_DIR / 'backups'
OUT_SUMMARY = ROOT / 'analyze' / 'jsons' / 'pruned-pages-summary.json'

if not REMOVED_URLS_FILE.exists():
    print('Missing removed list:', REMOVED_URLS_FILE)
    raise SystemExit(1)

removed = set([l.strip() for l in REMOVED_URLS_FILE.read_text(encoding='utf-8').splitlines() if l.strip()])
if not removed:
    print('No removed URLs found in', REMOVED_URLS_FILE)
    raise SystemExit(0)

now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
backup_root = BACKUP_DIR / now
summary = {'timestamp': now, 'files': [], 'total_removed': 0}

for cat_dir in [p for p in DATA_DIR.iterdir() if p.is_dir() and p.name not in ('__pycache__','backups')]:
    for src in sorted(cat_dir.glob('page-*.json')):
        try:
            data = json.loads(src.read_text(encoding='utf-8'))
        except Exception as e:
            print('Skipping', src, 'read error:', e)
            continue
        if not isinstance(data, list):
            continue
        orig_len = len(data)
        new_list = []
        removed_urls_here = []
        for it in data:
            url = None
            if isinstance(it, str):
                url = it
            elif isinstance(it, dict) and 'url' in it:
                url = it['url']
            if url and url in removed:
                removed_urls_here.append(url)
            else:
                new_list.append(it)
        if removed_urls_here:
            # backup original file
            dest = backup_root / src.relative_to(DATA_DIR)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            # write new file
            src.write_text(json.dumps(new_list, indent=2, ensure_ascii=False), encoding='utf-8')
            count_removed = len(removed_urls_here)
            summary['files'].append({'path': str(src), 'orig': orig_len, 'new': len(new_list), 'removed': count_removed, 'removed_urls': removed_urls_here})
            summary['total_removed'] += count_removed

OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
OUT_SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
print('Prune complete:', summary['total_removed'], 'URLs removed; summary written to', OUT_SUMMARY)
print('Backups in', backup_root)

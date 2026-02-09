#!/usr/bin/env python3
"""Extract script URLs from page-*.json files in pinescript_downloads and write
combined deduplicated lists into analyze/jsons/.

Usage:
  python analyze/extract_urls.py
  python analyze/extract_urls.py --categories indicators libraries

Output files:
  analyze/jsons/indicators-urls.json
  analyze/jsons/libraries-urls.json
  analyze/jsons/strategies-urls.json
"""
from pathlib import Path
import json
import argparse

ROOT = Path(__file__).parent
OUT_DIR = ROOT / 'jsons'
OUT_DIR.mkdir(exist_ok=True)
DATA_DIR = Path('pinescript_downloads')
CATS = ['indicators','libraries','strategies']


def load_urls_for_category(cat: str):
    p = DATA_DIR / cat
    if not p.exists() or not p.is_dir():
        return []
    urls = []
    for f in sorted(p.glob('page-*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        for it in data:
            if isinstance(it, str):
                urls.append(it)
            elif isinstance(it, dict) and 'url' in it:
                urls.append(it['url'])
    return urls


def write_output(cat: str, urls):
    out = OUT_DIR / f'{cat}-urls.json'
    out.write_text(json.dumps(urls, indent=2), encoding='utf-8')
    print(f'Wrote {out} ({len(urls)} urls)')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--categories', '-c', nargs='+', default=CATS, help='categories to process')
    parser.add_argument('--dedupe', action='store_true', help='deduplicate URLs (defaults to keeping order)')
    args = parser.parse_args()

    for cat in args.categories:
        urls = load_urls_for_category(cat)
        if args.dedupe:
            seen = set(); uniq = []
            for u in urls:
                if u not in seen:
                    seen.add(u); uniq.append(u)
            urls = uniq
        write_output(cat, urls)

if __name__ == '__main__':
    main()

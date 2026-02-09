#!/usr/bin/env python3
"""Build a combined, deduplicated all-urls.json from per-category url files.

Usage:
  python analyze/build_all_urls.py --categories indicators libraries strategies --output analyze/jsons/all-urls.json
"""
from pathlib import Path
import json
import argparse

ROOT = Path(__file__).parent
OUT_DIR = ROOT / 'jsons'
OUT_DIR.mkdir(exist_ok=True)

DEFAULT_CATS = ['indicators','libraries','strategies']


def load_cat_urls(cat: str):
    p = ROOT / 'jsons' / f'{cat}-urls.json'
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        # fallback: read as plain lines
        return [ln.strip() for ln in p.read_text(encoding='utf-8').splitlines() if ln.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--categories', '-c', nargs='+', default=DEFAULT_CATS)
    parser.add_argument('--output', '-o', default=str(OUT_DIR / 'all-urls.json'))
    args = parser.parse_args()

    seen = set(); out = []
    for cat in args.categories:
        for u in load_cat_urls(cat):
            if u not in seen:
                seen.add(u); out.append(u)

    out_path = Path(args.output)
    out_path.write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f'Wrote {out_path} ({len(out)} urls)')


if __name__ == '__main__':
    main()

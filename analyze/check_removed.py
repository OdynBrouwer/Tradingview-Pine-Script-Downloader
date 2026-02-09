#!/usr/bin/env python3
"""Check for removed/ghosted TradingView publications (light HTTP check).

Usage examples:
  # single URL check
  python analyze/check_removed.py --url "https://www.tradingview.com/script/0h5CiuCK-3-Period-Momentum-Composite/"

  # scan all local .pine files under pinescript_downloads and write report
  python analyze/check_removed.py --scan --output analyze/jsons/removed.json

The script performs a simple GET request (no JS) and looks for common removal markers
in the HTTP status, <title> tag or page text. It's intentionally lightweight to be
used as a periodic monitor.
"""
from __future__ import annotations
import argparse
import json
import re
import time
from pathlib import Path
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
PINES_DIR = Path('pinescript_downloads')
OUT_DIR = ROOT / 'jsons'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# markers to consider the publication removed/ghosted
REMOVAL_MARKERS = [
    'publication not found',
    'publication has ghosted',
    'publication has been removed',
    'removed by moderator',
    'removed by moderators',
    'this publication has been removed',
    'publication has been deleted',
    'page not found',
    '404 - not found',
    'publication not found on this page',
    "can't find the publication",
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}


def find_urls_from_pines() -> List[Dict[str, str]]:
    out = []
    if not PINES_DIR.exists():
        return out
    for p in PINES_DIR.rglob('*.pine'):
        text = p.read_text(encoding='utf-8', errors='ignore')
        url = None
        for ln in text.splitlines()[:40]:
            if ln.startswith('// URL:'):
                url = ln.split(':', 1)[1].strip()
                break
        if url:
            out.append({'url': url, 'pine_path': str(p)})
    return out


def check_url(url: str, timeout: float = 15.0) -> Dict:
    out = {'url': url, 'status': None, 'removed': False, 'reason': None, 'title': None, 'snippet': None}
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
    except Exception as e:
        out.update({'status': None, 'removed': False, 'reason': f'error:{e}'})
        return out

    out['status'] = r.status_code
    text = r.text or ''

    # parse title and small snippet
    try:
        soup = BeautifulSoup(text, 'html.parser')
        title = soup.title.string.strip() if soup.title and soup.title.string else ''
        out['title'] = title
        # small content snippet, first 200 chars of body text
        body = soup.get_text(separator=' ', strip=True)
        out['snippet'] = (body[:200] + '...') if len(body) > 200 else body
    except Exception:
        out['title'] = None
        out['snippet'] = text[:200]

    # quick heuristics
    lc = (out.get('title') or '') + '\n' + (out.get('snippet') or '')
    lc = lc.lower()

    if r.status_code in (404, 410):
        out['removed'] = True
        out['reason'] = f'status:{r.status_code}'
        return out

    for marker in REMOVAL_MARKERS:
        if marker in lc:
            out['removed'] = True
            out['reason'] = f'marker:{marker}'
            return out

    # If the page contains the specific phrase 'Publication not found' capitalized in header
    if re.search(r'publication\s+not\s+found', lc, re.I):
        out['removed'] = True
        out['reason'] = 'marker:publication not found'
        return out

    return out


def run_scan(urls: List[Dict[str, str]], delay: float = 0.5) -> List[Dict]:
    results = []
    for i, item in enumerate(urls, start=1):
        url = item['url']
        pine_path = item.get('pine_path')
        print(f'[{i}/{len(urls)}] Checking {url}', end='\r')
        res = check_url(url)
        res['pine_path'] = pine_path
        results.append(res)
        time.sleep(delay)
    print()
    return results


def write_results(results: List[Dict], out_json: Path, out_txt: Path):
    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    removed = [r['url'] for r in results if r.get('removed')]
    out_txt.write_text('\n'.join(removed), encoding='utf-8')
    print(f'Wrote {out_json} ({len(results)} entries) and {out_txt} ({len(removed)} removed)')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan', action='store_true', help='Scan all local .pine URLs')
    parser.add_argument('--url', help='Single URL to check')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between requests (seconds)')
    parser.add_argument('--output', default=str(OUT_DIR / 'removed.json'))
    args = parser.parse_args()

    to_check = []
    if args.url:
        to_check.append({'url': args.url, 'pine_path': None})
    if args.scan:
        to_check.extend(find_urls_from_pines())

    if not to_check:
        parser.error('nothing to do: provide --url or --scan')

    results = run_scan(to_check, delay=args.delay)
    out_json = Path(args.output)
    out_txt = out_json.with_name(out_json.stem + '-urls.txt')
    write_results(results, out_json, out_txt)


if __name__ == '__main__':
    main()

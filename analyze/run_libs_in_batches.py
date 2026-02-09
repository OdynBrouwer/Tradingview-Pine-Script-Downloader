#!/usr/bin/env python3
"""Run the existing `scrape_pubdates.py` over library URLs in batches.

Produces per-batch files `lib-pubdates-part-<i>.json` inside the `analyze` folder
and a combined `lib-pubdates.json` with all results.

Usage: python analyze/run_libs_in_batches.py --batch-size 100 --delay 1.0 --start-batch 1
"""
import argparse
import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
# by default operate on 'libraries' but support indicators/strategies via --category
LIB_DIR = Path('pinescript_downloads')
OUT_DIR = ROOT / 'jsons'
OUT_DIR.mkdir(exist_ok=True)
SCRAPER = ROOT / 'scrape_pubdates.py'


def load_urls(category: str):
    # Prefer pre-extracted list in analyze/jsons if present
    pre = OUT_DIR / f'{category}-urls.json'
    if pre.exists():
        data = json.loads(pre.read_text(encoding='utf-8'))
        urls = [u for u in data if isinstance(u, str)]
        return urls

    # Fallback: scan pinescript_downloads/<category>/page-*.json
    pdir = LIB_DIR / category
    urls = []
    for p in sorted(pdir.glob('page-*.json')):
        data = json.loads(p.read_text(encoding='utf-8'))
        for it in data:
            if isinstance(it, str):
                urls.append(it)
            elif isinstance(it, dict) and 'url' in it:
                urls.append(it['url'])
    return urls


def load_downloaded_urls(category: str):
    """Return a set of URLs that already have a downloaded .pine file under pinescript_downloads/<category>"""
    pdir = LIB_DIR / category
    found = set()
    if not pdir.exists():
        return found
    for f in pdir.rglob('*.pine'):
        try:
            txt = f.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for ln in txt.splitlines():
            if ln.startswith('// URL:'):
                found.add(ln.split(':',1)[1].strip())
                break
    return found


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--category', '-c', choices=['libraries','indicators','strategies'], default='libraries', help='which category to process')
    parser.add_argument('--batch-size', '-b', type=int, default=100)
    parser.add_argument('--delay', '-d', type=float, default=1.0)
    parser.add_argument('--concurrency', type=int, default=1, help='concurrency to pass to scraper')
    parser.add_argument('--jitter', type=float, default=0.2, help='jitter to pass to scraper')
    parser.add_argument('--retries', type=int, default=2, help='retries to pass to scraper')
    parser.add_argument('--only-downloaded', action='store_true', help='only process urls that already have a downloaded .pine file')
    parser.add_argument('--start-batch', type=int, default=1, help='resume from this batch index (1-based)')
    parser.add_argument('--no-cleanup', action='store_true')
    parser.add_argument('--force', action='store_true', help='do not skip urls already present in merged file')
    args = parser.parse_args()

    urls = load_urls(args.category)

    # optionally filter to only those URLs that already have a downloaded .pine file
    if args.only_downloaded:
        downloaded = load_downloaded_urls(args.category)
        orig_total = len(urls)
        urls = [u for u in urls if u in downloaded]
        print(f'Filtering to only downloaded .pine files: {len(urls)}/{orig_total} URLs will be processed')

    # exclude already-scraped urls if {category}-pubdates.json exists and not --force
    merged = OUT_DIR / f'{args.category}-pubdates.json'
    seen = set()
    if merged.exists() and not args.force:
        try:
            data = json.loads(merged.read_text(encoding='utf-8'))
            for it in data:
                if isinstance(it, dict) and 'url' in it:
                    seen.add(it['url'])
        except Exception:
            pass
    orig_total = len(urls)
    urls = [u for u in urls if u not in seen]
    total = len(urls)
    skipped = orig_total - total
    print(f'Category: {args.category} — {orig_total} URLs found, {skipped} skipped (already present), {total} to process, running in batches of {args.batch_size} (start at batch {args.start_batch})...')

    parts = []
    for idx, part in enumerate(chunk(urls, args.batch_size), start=1):
        if idx < args.start_batch:
            out = ROOT / f'lib-pubdates-part-{idx:04d}.json'
            if out.exists():
                print(f'Skipping batch {idx} (already exists)')
                parts.append(out)
                continue
            else:
                print(f'Skipping batch {idx} (start-batch set), but file missing; it will be produced when running from beginning')
                continue

        tmp = OUT_DIR / f'tmp-{args.category}-batch-{idx:04d}.json'
        out = OUT_DIR / f'{args.category}-pubdates-part-{idx:04d}.json'

        if out.exists():
            print(f'Batch {idx} output {out.name} already exists in {OUT_DIR}, skipping')
            parts.append(out)
            continue

        tmp.write_text(json.dumps(part, indent=2), encoding='utf-8')
        print(f'Running batch {idx} ({len(part)} URLs) -> {OUT_DIR / out.name}')
        cmd = ['python', str(SCRAPER), '--input', str(tmp), '--output', str(out), '--delay', str(args.delay), '--concurrency', str(args.concurrency), '--jitter', str(args.jitter), '--retries', str(args.retries)]
        subprocess.run(cmd, check=True)
        parts.append(out)
        if not args.no_cleanup:
            try:
                tmp.unlink()
            except Exception:
                pass

    # Merge parts
    combined = []
    for p in parts:
        combined.extend(json.loads(p.read_text(encoding='utf-8')))

    out_all = OUT_DIR / f'{args.category}-pubdates.json'
    out_all.write_text(json.dumps(combined, default=str, indent=2), encoding='utf-8')
    print('Wrote', out_all)


if __name__ == '__main__':
    main()

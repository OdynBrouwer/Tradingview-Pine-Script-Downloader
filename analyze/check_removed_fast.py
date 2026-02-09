#!/usr/bin/env python3
"""Fast parallel checker for removed/ghosted TradingView scripts.

Features:
- Async, concurrency with aiohttp
- HEAD-first optimization to quickly detect 404/410
- Partial GET streaming (reads up to `--read-bytes` bytes) to find removal markers in the title/body
- Progress file for resume (writes processed URLs)
- Option to check only missing URLs from `analyze/jsons/missing-pubdates-urls.txt`

Usage examples:
  python analyze/check_removed_fast.py --only-missing --concurrency 12 --head-first --timeout 8 --progress analyze/jsons/removed-progress.json --output analyze/jsons/removed-fast.json

"""
from __future__ import annotations
import argparse
import asyncio
import json
import re
import signal
import sys
from pathlib import Path
from typing import List, Dict, Optional

import aiohttp

ROOT = Path(__file__).parent
PINES_DIR = Path('pinescript_downloads')
OUT_DIR = ROOT / 'jsons'
OUT_DIR.mkdir(parents=True, exist_ok=True)

REMOVAL_MARKERS = [
    'publication not found',
    'publication has ghosted',
    'publication has been removed',
    'removed by moderator',
    'removed by moderators',
    "this publication has been removed",
    'publication has been deleted',
    'page not found',
    '404 - not found',
]

TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# Graceful cancellation
SHOULD_STOP = False


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


async def fetch_head(session: aiohttp.ClientSession, url: str, timeout: int) -> Optional[int]:
    try:
        async with session.head(url, timeout=timeout) as r:
            return r.status
    except Exception:
        return None


async def fetch_partial(session: aiohttp.ClientSession, url: str, timeout: int, read_bytes: int) -> Dict:
    """Return dict with status, title (maybe), snippet (partial body)."""
    out = {'status': None, 'title': None, 'snippet': ''}
    try:
        async with session.get(url, timeout=timeout) as r:
            out['status'] = r.status
            # read up to read_bytes bytes from the body
            collected = bytearray()
            try:
                async for chunk in r.content.iter_chunked(1024):
                    collected.extend(chunk)
                    if len(collected) >= read_bytes:
                        break
            except Exception:
                pass
            text = collected.decode('utf-8', errors='replace')
            # extract title quickly
            m = TITLE_RE.search(text)
            if m:
                out['title'] = m.group(1).strip()
            # body snippet - lowercased for marker checks
            out['snippet'] = text[:2000]
            return out
    except Exception:
        return out


async def worker(name: int, queue: asyncio.Queue, session: aiohttp.ClientSession, results: List[Dict], sem: asyncio.Semaphore, progress: Dict, args):
    global SHOULD_STOP
    while not queue.empty() and not SHOULD_STOP:
        item = await queue.get()
        url = item['url']
        pine_path = item.get('pine_path')
        if url in progress.get('done', {}):
            queue.task_done()
            continue
        async with sem:
            # HEAD-first check
            status = None
            if args.head_first:
                status = await fetch_head(session, url, timeout=args.timeout)
                # If HEAD indicates removed, record and move on
                if status in (404, 410):
                    res = {'url': url, 'status': status, 'removed': True, 'reason': f'status:{status}', 'title': None, 'snippet': None, 'pine_path': pine_path}
                    results.append(res)
                    progress['done'][url] = res
                    queue.task_done()
                    continue
            # Otherwise do partial GET
            info = await fetch_partial(session, url, timeout=args.timeout, read_bytes=args.read_bytes)
            status = status or info.get('status')
            title = info.get('title')
            snippet = (info.get('snippet') or '')
            lc = ((title or '') + '\n' + snippet).lower()
            removed = False
            reason = None
            if status in (404, 410):
                removed = True
                reason = f'status:{status}'
            else:
                for marker in REMOVAL_MARKERS:
                    if marker in lc:
                        removed = True
                        reason = f'marker:{marker}'
                        break
                # also check for short phrase 'publication not found' specifically
                if not removed and re.search(r'publication\s+not\s+found', lc, re.I):
                    removed = True
                    reason = 'marker:publication not found'
            from datetime import datetime, timezone
            res = {'url': url, 'status': status, 'removed': removed, 'reason': reason, 'title': title, 'snippet': snippet[:1000], 'pine_path': pine_path, 'last_checked': datetime.now(timezone.utc).isoformat()}
            results.append(res)
            progress['done'][url] = res
        queue.task_done()


async def run(urls: List[Dict[str, str]], args) -> List[Dict]:
    global SHOULD_STOP
    results: List[Dict] = []
    progress = {'done': {}}

    # load progress if present
    if args.progress and Path(args.progress).exists():
        try:
            progress = json.loads(Path(args.progress).read_text(encoding='utf-8'))
        except Exception:
            progress = {'done': {}}

    q = asyncio.Queue()
    for item in urls:
        q.put_nowait(item)

    sem = asyncio.Semaphore(args.concurrency)

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=args.timeout, sock_read=args.timeout)
    connector = aiohttp.TCPConnector(limit=0, ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS, connector=connector) as session:
        # start workers
        tasks = []
        for i in range(args.concurrency):
            t = asyncio.create_task(worker(i, q, session, results, sem, progress, args))
            tasks.append(t)

        # handle signals
        def _cancel():
            global SHOULD_STOP
            SHOULD_STOP = True
            for t in tasks:
                t.cancel()
        # Try to register signal handlers; on Windows add_signal_handler may not be implemented
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, _cancel)
            loop.add_signal_handler(signal.SIGTERM, _cancel)
        except NotImplementedError:
            # Fallback: use signal.signal where available (SIGTERM may not exist on Windows)
            try:
                signal.signal(signal.SIGINT, lambda s, f: _cancel())
            except Exception:
                pass
            try:
                signal.signal(signal.SIGTERM, lambda s, f: _cancel())
            except Exception:
                pass

        try:
            await q.join()
        except asyncio.CancelledError:
            pass
        finally:
            # write progress
            if args.progress:
                Path(args.progress).write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding='utf-8')

        # cancel remaining tasks
        for t in tasks:
            t.cancel()

    return results


def rebuild_missing_urls_file(out_path: Path) -> List[str]:
    """Scan local .pine files and write missing-pubdates-urls.txt with URLs that lack // Published:"""
    urls = []
    if not PINES_DIR.exists():
        return urls
    for p in PINES_DIR.rglob('*.pine'):
        txt = p.read_text(encoding='utf-8', errors='ignore')
        header = [ln for ln in txt.splitlines()[:40] if ln.startswith('//')]
        has_pub = any(ln.startswith('// Published:') for ln in header)
        url = None
        for ln in header:
            if ln.startswith('// URL:'):
                url = ln.split(':', 1)[1].strip()
                break
        if url and not has_pub:
            urls.append(url)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(sorted(set(urls))), encoding='utf-8')
    print(f'Wrote {out_path} ({len(urls)} entries)')
    return urls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only-missing', action='store_true', help='Check only URLs from analyze/jsons/missing-pubdates-urls.txt')
    parser.add_argument('--rebuild-missing', action='store_true', help='Rebuild missing-pubdates-urls.txt from current .pine files before running')
    parser.add_argument('--concurrency', type=int, default=12)
    parser.add_argument('--head-first', action='store_true', help='Do HEAD request first to quickly detect 404/410')
    parser.add_argument('--timeout', type=int, default=8)
    parser.add_argument('--read-bytes', type=int, default=16*1024, help='Max bytes to read from body')
    parser.add_argument('--output', default=str(OUT_DIR / 'removed-fast.json'))
    parser.add_argument('--progress', default=str(OUT_DIR / 'removed-progress.json'))
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--source', default=str(OUT_DIR / 'all-urls.json'), help='Source file of URLs (JSON array or file path)')
    parser.add_argument('--only-new', action='store_true', help='Check only URLs not in progress (incremental)')
    parser.add_argument('--max-age-days', type=int, default=0, help='Re-check URLs older than N days')
    args = parser.parse_args()

    # If user requested a rebuild, regenerate missing-pubdates-urls.txt from current pines
    if args.rebuild_missing:
        missing_file = ROOT / 'jsons' / 'missing-pubdates-urls.txt'
        rebuild_missing_urls_file(missing_file)

    urls: List[Dict[str, str]] = []

    # Load URLs from a specified source file if present
    src_path = Path(args.source)
    if src_path.exists():
        try:
            data = json.loads(src_path.read_text(encoding='utf-8'))
            for it in data:
                if isinstance(it, str):
                    urls.append({'url': it, 'pine_path': None})
                elif isinstance(it, dict) and 'url' in it:
                    urls.append({'url': it['url'], 'pine_path': it.get('pine_path')})
        except Exception:
            # Not JSON or failed; treat as plain text list
            for ln in src_path.read_text(encoding='utf-8').splitlines():
                ln = ln.strip()
                if ln:
                    urls.append({'url': ln, 'pine_path': None})
    elif args.only_missing:
        p = ROOT / 'jsons' / 'missing-pubdates-urls.txt'
        if not p.exists():
            print('missing-pubdates-urls.txt not found; run analyze/extract_missing_pubdates.py first or use --rebuild-missing')
            sys.exit(1)
        for ln in p.read_text(encoding='utf-8').splitlines():
            ln = ln.strip()
            if ln:
                urls.append({'url': ln, 'pine_path': None})
    else:
        urls = find_urls_from_pines()

    # Load progress to filter incremental options
    progress = {}
    prog_path = Path(args.progress)
    if prog_path.exists():
        try:
            prog = json.loads(prog_path.read_text(encoding='utf-8'))
            progress = prog.get('done', {})
        except Exception:
            progress = {}

    # Apply --only-new or --max-age-days filtering
    from datetime import datetime, timedelta, timezone
    if args.only_new or args.max_age_days > 0:
        filtered = []
        now = datetime.now(timezone.utc)
        cutoff = None
        if args.max_age_days > 0:
            cutoff = now - timedelta(days=args.max_age_days)
        for item in urls:
            u = item['url']
            rec = progress.get(u)
            if args.only_new:
                if rec is None:
                    filtered.append(item)
            elif cutoff is not None:
                if rec is None:
                    filtered.append(item)
                else:
                    lc = rec.get('last_checked')
                    if not lc:
                        filtered.append(item)
                    else:
                        try:
                            lst = datetime.fromisoformat(lc)
                            if lst.tzinfo is None:
                                lst = lst.replace(tzinfo=timezone.utc)
                        except Exception:
                            filtered.append(item); continue
                        if lst < cutoff:
                            filtered.append(item)
        urls = filtered

    if args.limit > 0:
        urls = urls[:args.limit]

    print(f'Checking {len(urls)} URLs with concurrency={args.concurrency} head-first={args.head_first}')

    results = asyncio.run(run(urls, args))

    # Merge with existing progress if present and construct final results mapping (prefer latest last_checked)
    out_results_map = {}
    # load previous done entries
    if Path(args.progress).exists():
        try:
            prog = json.loads(Path(args.progress).read_text(encoding='utf-8'))
            for k, v in prog.get('done', {}).items():
                out_results_map[k] = v
        except Exception:
            pass
    # add/replace with newly fetched results
    for r in results:
        out_results_map[r['url']] = r

    out_results = list(out_results_map.values())

    out_json = Path(args.output)
    out_txt = out_json.with_name(out_json.stem + '-urls.txt')
    out_json.write_text(json.dumps(out_results, indent=2, ensure_ascii=False), encoding='utf-8')
    out_txt.write_text('\n'.join([r['url'] for r in out_results if r.get('removed')]), encoding='utf-8')
    print(f'Wrote {out_json} ({len(out_results)} entries) and {out_txt} ({len([r for r in out_results if r.get("removed")])} removed)')
    # update progress file to reflect merged done
    if args.progress:
        Path(args.progress).write_text(json.dumps({'done': out_results_map}, indent=2, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()

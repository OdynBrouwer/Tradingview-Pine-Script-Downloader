#!/usr/bin/env python3
"""Check for updated scripts by comparing remote published dates against local .pine headers.

Outputs:
 - analyze/jsons/updated-scripts.json
 - analyze/jsons/updated-scripts-urls.txt

Usage:
  python analyze/scripts/check_updates.py --source analyze/jsons/all-urls.json --concurrency 12
"""
import argparse
import asyncio
from pathlib import Path
import re
import json
import aiohttp
from datetime import datetime
import email.utils

ROOT = Path('.').resolve()
OUT_JSON = ROOT / 'analyze' / 'jsons' / 'updated-scripts.json'
OUT_TXT = ROOT / 'analyze' / 'jsons' / 'updated-scripts-urls.txt'

PUB_RFC_RE = re.compile(r"[A-Za-z]{3}, \s*\d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2} GMT")
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
UID_RE = re.compile(r"/script/([A-Za-z0-9]+)")

async def fetch_published(session, url, timeout=8):
    try:
        async with session.get(url, timeout=timeout) as resp:
            text = await resp.text()
            # try to find RFC date
            m = PUB_RFC_RE.search(text)
            if m:
                try:
                    dt = email.utils.parsedate_to_datetime(m.group(0))
                    return dt
                except Exception:
                    pass
            # try ISO
            m2 = ISO_RE.search(text)
            if m2:
                try:
                    # parse naive ISO
                    dt = datetime.fromisoformat(m2.group(0))
                    return dt
                except Exception:
                    pass
            # fallback: search for "Published: YYYY"
            idx = text.find('Published:')
            if idx!=-1:
                snippet = text[idx:idx+100]
                m3 = ISO_RE.search(snippet) or PUB_RFC_RE.search(snippet)
                if m3:
                    try:
                        # attempt parsing
                        if PUB_RFC_RE.search(m3.group(0)):
                            dt = email.utils.parsedate_to_datetime(m3.group(0))
                        else:
                            dt = datetime.fromisoformat(m3.group(0))
                        return dt
                    except Exception:
                        pass
            return None
    except Exception as e:
        return None


def find_local_pine(uid):
    # find files matching UID in pinescript_downloads
    root = ROOT / 'pinescript_downloads'
    if not root.exists():
        return None
    pattern = f"**/{uid}_*.pine"
    matches = list(root.glob(pattern)) + list(root.glob(f"**/{uid}.pine"))
    return [m for m in matches]


def parse_local_published(path: Path):
    try:
        txt = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return None
    for line in txt.splitlines()[:40]:
        if line.startswith('//') and 'Published:' in line:
            # format: // Published: 2026-02-05T12:22:04+00:00
            idx = line.find('Published:')
            val = line[idx+len('Published:'):].strip()
            # try parsing
            try:
                if 'GMT' in val or ',' in val:
                    dt = email.utils.parsedate_to_datetime(val)
                else:
                    # try iso
                    # strip timezone Z
                    if val.endswith('Z'):
                        val = val[:-1]
                    dt = datetime.fromisoformat(val)
                return dt
            except Exception:
                continue
    return None

async def worker(queue, session, results):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done(); break
        url = item
        # extract uid
        m = UID_RE.search(url)
        uid = m.group(1) if m else None
        remote_dt = await fetch_published(session, url)
        local_files = find_local_pine(uid) if uid else []
        local_dt = None
        local_path = None
        if local_files:
            # pick latest by mtime
            lf = sorted(local_files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
            local_path = str(lf)
            local_dt = parse_local_published(lf)
        updated = False
        reason = None
        if remote_dt and local_dt:
            if remote_dt > local_dt:
                updated = True
                reason = f'remote_newer (remote={remote_dt.isoformat()}, local={local_dt.isoformat()})'
        elif remote_dt and not local_dt:
            updated = True
            reason = f'remote_has_date(local_missing) (remote={remote_dt.isoformat()})'
        # else: no remote date, or local newer
        if updated:
            results.append({'url': url, 'uid': uid, 'remote_published': remote_dt.isoformat() if remote_dt else None, 'local_published': local_dt.isoformat() if local_dt else None, 'local_path': local_path, 'reason': reason})
        queue.task_done()

async def main(source, concurrency):
    urls = json.loads(Path(source).read_text(encoding='utf-8'))
    q = asyncio.Queue()
    for u in urls:
        q.put_nowait(u)
    results = []
    async with aiohttp.ClientSession(headers={'User-Agent':'Mozilla/5.0'}) as session:
        tasks = [asyncio.create_task(worker(q, session, results)) for _ in range(concurrency)]
        await q.join()
        for _ in tasks:
            q.put_nowait(None)
        await asyncio.gather(*tasks)
    # write outputs
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    OUT_TXT.write_text('\n'.join([r['url'] for r in results]), encoding='utf-8')
    print('Updated scripts found:', len(results))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='analyze/jsons/all-urls.json')
    parser.add_argument('--concurrency', type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main(args.source, args.concurrency))

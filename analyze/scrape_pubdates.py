#!/usr/bin/env python3
"""Scrape publication dates from TradingView script pages and normalize to UTC timestamps.

Usage examples:
  python scripts/scrape_pubdates.py --input pinescript_downloads/page-01/page-01-urls.json --sample 10 --output pubdates_page01.json --delay 1.5

Notes:
- Respects a delay between requests to avoid hammering the site.
- Supports relative times like "6 days ago" and absolute formats like "Dec 3, 2025".
"""
import argparse
import asyncio
import json
import re
import email.utils
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import random

from playwright.async_api import async_playwright

ROOT = Path(__file__).parent
OUT_DIR = ROOT / 'jsons'
OUT_DIR.mkdir(exist_ok=True)

REL_RE = re.compile(r"(?P<num>\d+)\s+(?P<unit>second|minute|hour|day|week|month|year)s?\s+ago", re.I)
ABS_MONTH_DAY_YEAR = re.compile(r"^(?P<mon>\w{3,9})\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})$")
# Accept month+day without year (e.g. 'Jan 18') and interpret as current year (or previous year if it would be in the future)
ABS_MONTH_DAY = re.compile(r"^(?P<mon>\w{3,9})\s+(?P<day>\d{1,2})$")

MONTHS = {m: i for i, m in enumerate(['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'], start=1)}


def parse_pubtext(pubtext: str):
    """Return a UTC datetime if parsable, else None. Also return normalized raw text."""
    if not pubtext:
        return None, None
    s = pubtext.strip()
    # Common relative form like '6 days ago' or '6 days ago' with extra text
    m = REL_RE.search(s)
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    if m:
        num = int(m.group('num'))
        unit = m.group('unit').lower()
        if unit.startswith('second'):
            dt = now - timedelta(seconds=num)
        elif unit.startswith('minute'):
            dt = now - timedelta(minutes=num)
        elif unit.startswith('hour'):
            dt = now - timedelta(hours=num)
        elif unit.startswith('day'):
            dt = now - timedelta(days=num)
        elif unit.startswith('week'):
            dt = now - timedelta(weeks=num)
        elif unit.startswith('month'):
            # approximate month as 30 days
            dt = now - timedelta(days=30 * num)
        elif unit.startswith('year'):
            dt = now - timedelta(days=365 * num)
        else:
            return None, s
        return dt.astimezone(timezone.utc), s

    # Absolute like 'Dec 3, 2025' or 'Sep 4, 2025'
    m2 = ABS_MONTH_DAY_YEAR.match(s)
    if m2:
        mon = m2.group('mon')[:3].title()
        day = int(m2.group('day'))
        year = int(m2.group('year'))
        # Map full month names too
        try:
            month_num = {**{k:k for k in []}}  # placeholder
            month_num = { 'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
            if mon in month_num:
                dt = datetime(year, month_num[mon], day, tzinfo=timezone.utc)
                return dt, s
        except Exception:
            pass

    # Month+Day (e.g. 'Jan 18') — assume current year, but if that date is in the (near) future assume previous year
    m3 = ABS_MONTH_DAY.match(s)
    if m3:
        mon = m3.group('mon')[:3].title()
        day = int(m3.group('day'))
        try:
            if mon in MONTHS:
                year = now.year
                dt = datetime(year, MONTHS[mon], day, tzinfo=timezone.utc)
                if dt > now + timedelta(days=1):
                    dt = datetime(year-1, MONTHS[mon], day, tzinfo=timezone.utc)
                return dt, s
        except Exception:
            pass

    # ISO-like strings
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc), s
    except Exception:
        pass

    # RFC-2822 / HTTP-date forms like 'Tue, 27 Jan 2026 17:08:30 GMT'
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc), s
    except Exception:
        pass

    # Some pages show just '6 days ago' or 'Today' or 'Yesterday'
    s_low = s.lower()
    if s_low.startswith('today'):
        dt = datetime.utcnow().replace(tzinfo=timezone.utc)
        return dt, s
    if s_low.startswith('yesterday'):
        dt = (datetime.utcnow() - timedelta(days=1)).replace(tzinfo=timezone.utc)
        return dt, s

    return None, s


async def extract_pubtext(page):
    # Try multiple selectors and fallbacks
    # 0) special handling for <relative-time> which often exposes attributes like event-time / ssr-time
    rel = await page.evaluate("() => { try { const el = document.querySelector('relative-time'); if(!el) return ''; const attrs = ['event-time','ssr-time','datetime','title']; for(const a of attrs){ const v = el.getAttribute(a); if(v) return v; } return el.textContent ? el.textContent.trim() : ''; } catch(e){} return ''; }")
    if rel:
        return rel

    # 1) <time> element — prefer machine-readable attributes (datetime, title, pubdate) then text
    t = await page.evaluate("() => { const el=document.querySelector('time'); if(!el) return ''; const attrs = ['datetime','title','pubdate','data-time']; for (const a of attrs) { try { const v = el.getAttribute(a); if (v) return v; } catch(e){} } return el.textContent ? el.textContent.trim() : ''; }")
    if t:
        return t

    # 2) explicit 'ago' search: return the matching relative substring (e.g. '6 days ago') when present
    ago = await page.evaluate("() => { try { const nodes = Array.from(document.querySelectorAll('div, span, p, li, small, a')); for (const n of nodes) { const t = (n.textContent||'').trim(); if (/\\bago\\b/i.test(t)) { const m = t.match(/\\d+\\s+(?:second|minute|hour|day|week|month|year)s?\\s+ago/i); return m ? m[0] : t; } } } catch(e){} return ''; }")
    if ago:
        return ago

    # 3) header small/date element near title: find any element that looks like a date (month names, 'ago')
    txt = await page.evaluate("() => { try { const nodes=Array.from(document.querySelectorAll('div, span, p')); for (const n of nodes) { const t=n.textContent||''; if(t && /\\b(ago|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\b/i.test(t)) return t.trim(); } } catch(e){} return ''; }")
    if txt:
        return txt

    # 4) meta tags
    meta = await page.evaluate("() => { const m = document.querySelector('meta[property=\"article:published_time\"]') || document.querySelector('meta[name=\"pubdate\"]') || document.querySelector('meta[name=\"date\"]'); return m ? (m.getAttribute('content')||m.getAttribute('value')||m.content||'') : '' }")
    if meta:
        return meta
    return ''


async def worker(browser, url, delay, jitter, retries):
    attempt = 0
    while True:
        attempt += 1
        page = await browser.new_page()
        try:
            # small random jitter to avoid synchronous bursts
            if jitter and jitter > 0:
                await asyncio.sleep(random.uniform(0, jitter))

            response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            status = response.status if response is not None else None
            if status is not None and status >= 400:
                raise Exception(f'HTTP {status}')

            # small wait for dynamic content
            await page.wait_for_timeout(500)
            pubtext = await extract_pubtext(page)
            dt, norm = parse_pubtext(pubtext)
            return {'url': url, 'pubtext': pubtext, 'published_utc': dt.isoformat() if dt else None, 'normalized': norm}
        except Exception as e:
            # retry with exponential backoff
            if attempt <= retries:
                backoff = min(2 ** (attempt - 1), 8)
                await asyncio.sleep(backoff)
                continue
            return {'url': url, 'error': str(e)}
        finally:
            try:
                await page.close()
            except:
                pass


async def run(args):
    urls = []
    inp = Path(args.input)
    if inp.is_file():
        data = json.loads(inp.read_text(encoding='utf-8'))
        # expect list of urls or list of objects with url
        if isinstance(data, list):
            for it in data:
                if isinstance(it, str):
                    urls.append(it)
                elif isinstance(it, dict) and 'url' in it:
                    urls.append(it['url'])
    elif inp.is_dir():
        # walk page-*.json
        for p in sorted(inp.glob('page-*.json')):
            urls.extend([u if isinstance(u,str) else u.get('url') for u in json.loads(p.read_text(encoding='utf-8'))])
    else:
        raise SystemExit('input must be a file or directory')

    if args.sample:
        urls = urls[:args.sample]

    results = [None] * len(urls)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            sem = asyncio.Semaphore(args.concurrency)

            async def run_one(i, url):
                async with sem:
                    print(f'[{i}/{len(urls)}] {url}')
                    r = await worker(browser, url, args.delay, args.jitter, args.retries)
                    results[i-1] = r

            tasks = [asyncio.create_task(run_one(i, u)) for i, u in enumerate(urls, 1)]
            # allow tasks to run with concurrency controlled by semaphore
            await asyncio.gather(*tasks)
        finally:
            await browser.close()

    out = Path(args.output)
    # if output is just a filename (no parent folder), write it into analyze/jsons/
    if out.parent == Path('.') or str(out).count(os.sep) == 0:
        out = OUT_DIR / out.name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, default=str, indent=2), encoding='utf-8')
    print('Wrote', out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', '-i', required=True, help='input json file (list) or directory with page-XX json files')
    parser.add_argument('--output', '-o', default='pubdates.json')
    parser.add_argument('--sample', '-n', type=int, default=0)
    parser.add_argument('--delay', type=float, default=1.0)
    parser.add_argument('--concurrency', type=int, default=1, help='number of concurrent pages to open')
    parser.add_argument('--jitter', type=float, default=0.2, help='max random jitter (seconds) before each request')
    parser.add_argument('--retries', type=int, default=2, help='number of retries on error')
    args = parser.parse_args()
    # allow analyze scripts to place outputs in analyze/jsons by default
    asyncio.run(run(args))


if __name__ == '__main__':
    main()

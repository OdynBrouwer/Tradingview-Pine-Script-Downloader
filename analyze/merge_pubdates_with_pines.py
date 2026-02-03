#!/usr/bin/env python3
"""Merge scraped pubdates with Pine file headers and optionally normalize headers.

Outputs: analyze/jsons/pubdates-merged.json

Usage:
  python analyze/merge_pubdates_with_pines.py        # dry-run report
  python analyze/merge_pubdates_with_pines.py --apply  # also update .pine headers to ISO format
"""
from pathlib import Path
import json
import re
import argparse
from datetime import datetime, timedelta, timezone
import email.utils

ROOT = Path(__file__).parent
OUT_DIR = ROOT / 'jsons'
PINES_DIR = Path('pinescript_downloads')

REL_RE = re.compile(r"(?P<num>\d+)\s+(?P<unit>second|minute|hour|day|week|month|year)s?\s+ago", re.I)
ABS_MONTH_DAY_YEAR = re.compile(r"^(?P<mon>\w{3,9})\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})$")
MONTHS = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}


def parse_date_string(s: str):
    if not s: return None
    s = s.strip()
    # relative
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
            dt = now - timedelta(days=30*num)
        elif unit.startswith('year'):
            dt = now - timedelta(days=365*num)
        else:
            return None
        return dt.astimezone(timezone.utc).isoformat()
    # absolute like 'Dec 3, 2025'
    m2 = ABS_MONTH_DAY_YEAR.match(s)
    if m2:
        mon = m2.group('mon')[:3].title()
        day = int(m2.group('day'))
        year = int(m2.group('year'))
        if mon in MONTHS:
            dt = datetime(year, MONTHS[mon], day, tzinfo=timezone.utc)
            return dt.isoformat()
    # iso
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    # rfc
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    # today/yesterday
    sl = s.lower()
    if sl.startswith('today'):
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    if sl.startswith('yesterday'):
        return (datetime.utcnow() - timedelta(days=1)).replace(tzinfo=timezone.utc).isoformat()
    return None


def load_scraped_pubdates():
    data = {}
    # find any *-pubdates.json in analyze/jsons
    for p in OUT_DIR.glob('*-pubdates*.json'):
        try:
            arr = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        for it in arr:
            url = it.get('url')
            if not url: continue
            # prefer published_utc field if present
            v = it.get('published_utc') or it.get('published_date') or it.get('pubtext')
            if v:
                iso = parse_date_string(v) or v
                data[url] = {'source_file': p.name, 'raw': v, 'iso': iso}
    return data


def scan_pines():
    pine_map = {}
    for p in PINES_DIR.rglob('*.pine'):
        text = p.read_text(encoding='utf-8', errors='ignore')
        header_lines = []
        for ln in text.splitlines()[:40]:
            if ln.startswith('//'):
                header_lines.append(ln)
            else:
                break
        pub_raw = None
        url = None
        for ln in header_lines:
            if ln.startswith('// Published:'):
                pub_raw = ln.split(':',1)[1].strip()
            if ln.startswith('// URL:'):
                url = ln.split(':',1)[1].strip()
        if url:
            pine_map[url] = {'path': str(p), 'published_raw': pub_raw, 'published_iso': parse_date_string(pub_raw) if pub_raw else None}
    return pine_map


def main(apply_changes: bool = False):
    scraped = load_scraped_pubdates()
    pines = scan_pines()

    merged = []
    count_pine = 0
    count_from_scrape = 0
    count_missing = 0
    updates = 0

    for url, entry in {**scraped, **pines}.items():
        pine = pines.get(url)
        scr = scraped.get(url)
        chosen = None
        source = None
        raw = None
        # prefer pine header iso if exists
        if pine and pine.get('published_iso'):
            chosen = pine['published_iso']
            source = 'pine'
            raw = pine.get('published_raw')
            count_pine += 1
        elif scr and scr.get('iso'):
            chosen = scr['iso']
            source = 'scraper'
            raw = scr.get('raw')
            count_from_scrape += 1
        else:
            chosen = None
            source = 'missing'
            raw = (pine and pine.get('published_raw')) or (scr and scr.get('raw'))
            count_missing += 1

        merged.append({'url': url, 'published_iso': chosen, 'source': source, 'raw': raw, 'pine_path': pine.get('path') if pine else None})

        # Optionally update pine header to normalized ISO
        if apply_changes and pine and pine.get('path'):
            path = Path(pine['path'])
            txt = path.read_text(encoding='utf-8', errors='ignore')
            lines = txt.splitlines()
            new_lines = []
            replaced = False
            for ln in lines:
                if ln.startswith('// Published:'):
                    if chosen:
                        new_lines.append(f'// Published: {chosen}')
                    else:
                        new_lines.append(ln)
                    replaced = True
                else:
                    new_lines.append(ln)
            if not replaced and chosen:
                # insert after URL line if present or after first header block
                inserted = False
                out_lines = []
                for ln in new_lines:
                    out_lines.append(ln)
                    if not inserted and ln.startswith('// URL:'):
                        out_lines.append(f'// Published: {chosen}')
                        inserted = True
                new_lines = out_lines
            if new_lines != lines:
                path.write_text('\n'.join(new_lines)+"\n", encoding='utf-8')
                updates += 1

    out = OUT_DIR / 'pubdates-merged.json'
    out.write_text(json.dumps(merged, indent=2), encoding='utf-8')
    print(f'Merged entries: {len(merged)}; from pines: {count_pine}; from scrape: {count_from_scrape}; missing: {count_missing}; files updated: {updates}')

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='apply normalized Published headers into .pine files')
    args = parser.parse_args()
    main(apply_changes=args.apply)

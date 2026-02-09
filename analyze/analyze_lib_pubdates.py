#!/usr/bin/env python3
"""Analyze lib pubdates vs decoded base62 IDs.

Outputs a short summary: counts, missing dates, Pearson and Spearman correlations.
"""
import json
import re
import string
from datetime import datetime, timezone
from statistics import mean, pstdev
from collections import defaultdict
from pathlib import Path

ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase
ALPHA_MAP = {c:i for i,c in enumerate(ALPHABET)}


def base62_decode(s: str) -> int:
    v = 0
    for ch in s:
        v = v*62 + ALPHA_MAP[ch]
    return v


def extract_id_from_url(url: str) -> str:
    # Expect URL like https://www.tradingview.com/script/<slug>/
    m = re.search(r'/script/([^/]+)/', url)
    if not m:
        m = re.search(r'/script/([^/]+)$', url)
    if not m:
        return None
    slug = m.group(1)
    # id is prefix before first '-' if present
    idpart = slug.split('-')[0]
    # strip any non-base62 chars
    idpart = re.match(r'([A-Za-z0-9]+)', idpart)
    return idpart.group(1) if idpart else None


def rank(values):
    # return list of ranks (average ranks for ties), 1-based
    n = len(values)
    sorted_pairs = sorted([(v,i) for i,v in enumerate(values)], key=lambda x: x[0])
    ranks = [0]*n
    i=0
    while i<n:
        j=i
        while j+1<n and sorted_pairs[j+1][0]==sorted_pairs[i][0]:
            j+=1
        # values from i..j have same value
        avg_rank = (i+1 + j+1)/2.0
        for k in range(i,j+1):
            orig_idx = sorted_pairs[k][1]
            ranks[orig_idx] = avg_rank
        i = j+1
    return ranks


def pearsonr(x, y):
    if len(x) < 2:
        return None
    mx = mean(x); my = mean(y)
    cov = sum((xi-mx)*(yi-my) for xi,yi in zip(x,y))/len(x)
    sx = pstdev(x)
    sy = pstdev(y)
    if sx==0 or sy==0:
        return None
    return cov/(sx*sy)


def spearmanr(x,y):
    rx = rank(x)
    ry = rank(y)
    return pearsonr(rx, ry)


def main():
    ROOT = Path(__file__).parent
    OUT_DIR = ROOT / 'jsons'
    candidates = [OUT_DIR / 'lib-pubdates.json', Path('scripts/lib-pubdates.json'), ROOT / 'lib-pubdates.json']
    src = None
    for c in candidates:
        if c.exists():
            src = c
            break
    if not src:
        raise SystemExit('lib-pubdates.json not found in analyze/jsons, scripts/, or analyze/')

    data = json.loads(src.read_text(encoding='utf-8'))
    total = len(data)
    missing = 0
    rows = []
    for it in data:
        url = it.get('url')
        pub = it.get('published_utc')
        idstr = extract_id_from_url(url) if url else None
        if not pub:
            missing += 1
        else:
            try:
                dt = datetime.fromisoformat(pub)
                epoch = dt.timestamp()
            except Exception:
                epoch = None
        rows.append({'url':url,'id':idstr,'pub':pub,'epoch':epoch})

    has_date = [r for r in rows if r['epoch'] is not None and r['id']]
    no_date = [r for r in rows if r['epoch'] is None]
    no_id = [r for r in rows if not r['id']]

    # decode ids and make arrays
    ids_decoded = []
    epochs = []
    for r in has_date:
        try:
            dec = base62_decode(r['id'])
            ids_decoded.append(dec)
            epochs.append(r['epoch'])
        except Exception:
            no_id.append(r)

    print('Total entries:', total)
    print('Entries with published date:', len(has_date))
    print('Entries missing date:', len(no_date))
    print('Entries without parsable id:', len(no_id))

    # show some examples
    if no_date:
        print('\nSample missing-date URLs (5):')
        for r in no_date[:5]:
            print('-', r['url'])
    if no_id:
        print('\nSample no-id entries (5):')
        for r in no_id[:5]:
            print('-', r['url'])

    if ids_decoded and epochs:
        pr = pearsonr(ids_decoded, epochs)
        sr = spearmanr(ids_decoded, epochs)
        print('\nPearson r:', pr)
        print('Spearman rho:', sr)
    else:
        print('\nNot enough data for correlation')

    # quick bucket counts by year
    from collections import Counter
    years = Counter()
    for e in epochs:
        y = datetime.fromtimestamp(e, tz=timezone.utc).year
        years[y]+=1
    print('\nYear distribution (top 8):')
    for y,c in years.most_common(8):
        print(y, c)

if __name__=='__main__':
    main()

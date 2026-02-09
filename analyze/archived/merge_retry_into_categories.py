import json
from pathlib import Path
r = Path('analyze/jsons/failed-pubdates-retry2.json')
if not r.exists():
    raise SystemExit('retry file missing')
rarr = json.loads(r.read_text(encoding='utf-8'))
cats = ['indicators','libraries','strategies']
updated = 0
for cat in cats:
    f = Path(f'analyze/jsons/{cat}-pubdates.json')
    if f.exists():
        arr = json.loads(f.read_text(encoding='utf-8'))
    else:
        arr = []
    m = {it['url']:it for it in arr if 'url' in it}
    for it in rarr:
        u = it.get('url')
        if u in m:
            if m[u] != it:
                m[u] = it
                updated += 1
    new = list(m.values())
    f.write_text(json.dumps(new, indent=2, ensure_ascii=False), encoding='utf-8')
print('merged retry results into category files; updated entries:', updated)

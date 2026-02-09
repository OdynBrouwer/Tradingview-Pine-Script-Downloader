import json
from pathlib import Path
rpath = Path('analyze/jsons/failed-pubdates-retry2.json')
if not rpath.exists():
    raise SystemExit('retry file missing')
arr = json.load(rpath.open(encoding='utf-8'))
missing = [it for it in arr if not it.get('published_utc')]
Path('analyze/jsons/failed-pubdates.json').write_text(json.dumps(missing, indent=2, ensure_ascii=False), encoding='utf-8')
Path('analyze/jsons/failed-pubdates-urls.txt').write_text('\n'.join(it['url'] for it in missing), encoding='utf-8')
print('wrote failed-pubdates.json (',len(missing),') and failed-pubdates-urls.txt')

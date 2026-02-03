import json
from pathlib import Path
p=Path('analyze/jsons')
count_total=0
count_iso=0
for f in p.glob('*-pubdates*.json'):
    data=json.loads(f.read_text(encoding='utf-8'))
    for it in data:
        count_total+=1
        v=it.get('published_utc') or it.get('published_date') or it.get('pubtext')
        if v:
            try:
                from datetime import datetime
                datetime.fromisoformat(v)
                count_iso+=1
            except Exception:
                pass
print('pubdate files total entries',count_total,'with iso-like value',count_iso)

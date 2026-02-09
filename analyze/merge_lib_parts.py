#!/usr/bin/env python3
from pathlib import Path
import json

ROOT = Path(__file__).parent
OUT_DIR = ROOT / 'jsons'
OUT_DIR.mkdir(exist_ok=True)
parts = []
# collect parts from analyze/jsons, analyze/, and scripts/
parts.extend(sorted((OUT_DIR).glob('lib-pubdates-part-*.json')))
parts.extend(sorted(ROOT.glob('lib-pubdates-part-*.json')))
parts.extend(sorted(Path('scripts').glob('lib-pubdates-part-*.json')))
# deduplicate while preserving order
seen = set(); unique_parts = []
for p in parts:
    if p not in seen:
        seen.add(p); unique_parts.append(p)

combined = []
for p in unique_parts:
    try:
        combined.extend(json.loads(p.read_text(encoding='utf-8')))
    except Exception as e:
        print('Skipping', p, 'due to', e)

out = OUT_DIR / 'lib-pubdates.json'
out.write_text(json.dumps(combined, default=str, indent=2), encoding='utf-8')
print('Merged', len(unique_parts), 'parts ->', out, 'entries:', len(combined))

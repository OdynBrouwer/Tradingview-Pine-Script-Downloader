import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from pathlib import Path

root = Path('pinescript_downloads')
if not root.exists():
    print('No pinescript_downloads directory found; nothing to check')
    sys.exit(0)

mismatches = []
summary = {'total':0,'library':0,'strategy':0,'indicator':0}
for f in root.rglob('*.pine'):
    summary['total'] += 1
    try:
        text = f.read_text(encoding='utf-8')
    except Exception as e:
        print('Failed to read', f, e)
        continue
    lines = text.splitlines()
    type_line = None
    for ln in lines[:20]:
        if ln.strip().startswith('// Type:'):
            type_line = ln.strip()
            break
    header_type = None
    if type_line:
        header_type = type_line.split(':',1)[1].strip()
    # naive content detection
    body = '\n'.join(lines)
    is_lib = 'library(' in body.lower()
    is_str = 'strategy(' in body.lower()
    detected = 'Library' if is_lib else 'Strategy' if is_str else 'Indicator'
    summary_key = detected.lower()
    summary[summary_key] += 1
    if header_type != detected:
        mismatches.append((str(f), header_type, detected))

print('Summary:', summary)
if mismatches:
    print('\nMismatches found:')
    print('Count:', len(mismatches))
    for m in mismatches[:200]:
        print(m)
else:
    print('\nNo mismatches detected')

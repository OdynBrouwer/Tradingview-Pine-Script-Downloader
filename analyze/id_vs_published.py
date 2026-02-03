import re, pathlib
from datetime import datetime
import statistics
alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
alpha_map={c:i for i,c in enumerate(alphabet)}

def decode(s):
    v=0
    for ch in s:
        v=v*62+alpha_map[ch]
    return v

p=pathlib.Path('pinescript_downloads')
rows=[]
for f in p.rglob('*.pine'):
    name=f.name
    m=re.match(r'([A-Za-z0-9]+)_', name)
    if not m: continue
    idv=m.group(1)
    text=f.read_text(encoding='utf-8', errors='ignore')
    pub=None
    for ln in text.splitlines()[:20]:
        if ln.strip().startswith('// Published:'):
            pubstr=ln.split(':',1)[1].strip()
            if pubstr:
                pub=pubstr
            break
    if pub:
        # try parse ISO-like
        dt=None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f","%Y-%m-%dT%H:%M:%S","%Y-%m-%d"):
            try:
                dt=datetime.strptime(pub,fmt)
                break
            except:
                dt=None
        if dt:
            rows.append((idv, decode(idv), dt))

print('found', len(rows), 'with published dates')
if not rows:
    raise SystemExit
# compute correlation between decoded id and timestamp epoch
xs=[r[1] for r in rows]
ys=[r[2].timestamp() for r in rows]
# compute Spearman rank correlation
import scipy.stats as ss
spearman=ss.spearmanr(xs,ys)
pearson=ss.pearsonr(xs,ys)
print('spearman', spearman)
print('pearson', pearson)
# Show sample pairs
for r in sorted(rows, key=lambda x:x[1])[:10]:
    print(r[0], r[1], r[2].isoformat())
for r in sorted(rows, key=lambda x:x[1])[-10:]:
    print(r[0], r[1], r[2].isoformat())

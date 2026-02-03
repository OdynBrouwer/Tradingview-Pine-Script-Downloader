import string,re,pathlib
alphabet=string.digits+string.ascii_uppercase+string.ascii_lowercase
alpha_map={c:i for i,c in enumerate(alphabet)}

def decode(s):
    v=0
    for ch in s:
        v=v*62+alpha_map[ch]
    return v

p=pathlib.Path('pinescript_downloads')
ids=[]
for f in p.rglob('*.pine'):
    m=re.match(r'([A-Za-z0-9]+)_', f.name)
    if m:
        ids.append(m.group(1))

vals=[decode(s) for s in ids]
print('count', len(vals))
print('min', min(vals), 'max', max(vals))
vals_sorted=sorted(vals)
print('median', vals_sorted[len(vals)//2])
from collections import Counter
pairs=sorted(zip(vals, ids))
print('smallest ids', pairs[:5])
print('largest ids', pairs[-5:])
import statistics
diffs=[y-x for x,y in zip(vals,vals[1:])]
if diffs:
    print('avg diff', statistics.mean(diffs), 'stdev', statistics.pstdev(diffs))
else:
    print('no diffs')
from collections import defaultdict
byprefix=defaultdict(list)
for idv in ids:
    byprefix[idv[0]].append(idv)
for k in sorted(list(byprefix))[:8]:
    print('prefix',k,'count',len(byprefix[k]))

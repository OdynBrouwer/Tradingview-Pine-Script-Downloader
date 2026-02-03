import re, pathlib
from collections import Counter
p=pathlib.Path('pinescript_downloads')
ids=[]
for f in p.rglob('*.pine'):
    m=re.match(r'([A-Za-z0-9]+)_', f.name)
    if m:
        ids.append(m.group(1))

lens=[len(i) for i in ids]
print('sample ids:', ids[:20])
print('unique ids total:', len(set(ids)), 'collected ids total:', len(ids))
print('lengths hist:', sorted(Counter(lens).items()))
chars=set(''.join(ids))
print('charset size:', len(chars))
print('charset sorted sample (first 50):', ''.join(sorted(list(chars))[:50]))
char_counts=Counter(''.join(ids))
print('top 20 chars:', char_counts.most_common(20))
print('\nexamples:')
for idv in list(dict.fromkeys(ids))[:40]:
    print(idv)

import json,os,sys,re
from pathlib import Path
j=root=Path('pinescript_downloads').resolve()
rf='analyze/jsons/removed-fast.json'
j=json.load(open(rf,encoding='utf-8'))
removed=[e for e in j if e.get('removed')]
# gather all .pine files
pine_files=[p for p in root.rglob('*.pine')]
print('pine_files_count:',len(pine_files))
matches=[]
# Pre-read file contents (but avoid loading huge files); we'll search for title or url fragment
for e in removed:
    url=e.get('url','')
    title=e.get('title','')
    uid_match=re.search(r'/script/([A-Za-z0-9]+)/',url)
    uid=uid_match.group(1) if uid_match else None
    found=[]
    for p in pine_files:
        try:
            txt=p.read_text(encoding='utf-8',errors='ignore')
        except Exception:
            continue
        if uid and uid in txt:
            found.append(str(p))
            continue
        # search for title words
        tshort=title.split('—')[0].strip() if '—' in title else title
        if tshort and len(tshort)>5 and tshort.lower() in txt.lower():
            found.append(str(p))
            continue
        # search for full url
        if url in txt:
            found.append(str(p))
            continue
    if found:
        matches.append((url,title,found))

print('removed_entries:',len(removed))
print('matches_found:',len(matches))
for url,title,found in matches[:200]:
    print('\nURL:',url)
    print('Title:',title)
    for f in found:
        print('  ->',f)

# write a JSON with matches
out={'matches_count':len(matches),'matches':matches}
open('analyze/jsons/removed-local-matches.json','w',encoding='utf-8').write(json.dumps(out,indent=2,ensure_ascii=False))
print('\nWrote analyze/jsons/removed-local-matches.json')

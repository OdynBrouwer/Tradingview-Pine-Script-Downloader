from pathlib import Path
root=Path('pinescript_downloads')
miss=[]
count=0
for f in root.rglob('strategies/*.pine'):
    count+=1
    try:
        txt=f.read_text(encoding='utf-8')
    except Exception:
        continue
    lines=txt.splitlines()
    type_line=None
    for ln in lines[:30]:
        if ln.strip().lower().startswith('// type:'):
            type_line=ln.strip()
            break
    header_type=type_line.split(':',1)[1].strip() if type_line else None
    body='\n'.join(lines)
    detected='Strategy' if 'strategy(' in body.lower() else 'Library' if 'library(' in body.lower() else 'Indicator'
    if header_type!=detected:
        miss.append((str(f), header_type, detected))

print('Total strategies files scanned:', count)
print('Mismatches:', len(miss))
for m in miss[:200]:
    print(m)

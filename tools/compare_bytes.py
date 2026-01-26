from pathlib import Path
f1=Path('pinescript_downloads/Volume_Profile_correct_from_copy_clicpboard.pine')
f2=Path('pinescript_downloads/8jW3AO3z/8jW3AO3z_Volume_Profile_-_Density_of_Density_DAFE.pine')
if not f1.exists() or not f2.exists():
    print('files missing')
    raise SystemExit(1)

b1=f1.read_bytes()
b2=f2.read_bytes()
print('len1',len(b1),'len2',len(b2))
for i,(x,y) in enumerate(zip(b1,b2)):
    if x!=y:
        print('first diff at',i,'b1',hex(x),'b2',hex(y))
        print('around bytes:',b1[max(0,i-20):i+20])
        print('vs:',b2[max(0,i-20):i+20])
        # show heuristic: try decode segments
        print('\nsegment1 repr:',b1[max(0,i-20):i+20])
        try:
            print('segment1 decoded utf8:',b1[max(0,i-20):i+20].decode('utf-8'))
        except Exception as e:
            print('utf8 decode error',e)
        try:
            print('segment1 decoded latin1:',b1[max(0,i-20):i+20].decode('latin-1'))
        except Exception as e:
            print('latin1 decode error',e)
        try:
            print('segment2 decoded utf8:',b2[max(0,i-20):i+20].decode('utf-8'))
        except Exception as e:
            print('utf8 decode error for b2',e)
        try:
            print('segment2 decoded latin1:',b2[max(0,i-20):i+20].decode('latin-1'))
        except Exception as e:
            print('latin1 decode error for b2',e)
        break
else:
    if len(b1)!=len(b2):
        print('no byte diffs in prefix but lengths differ')
    else:
        print('files identical')

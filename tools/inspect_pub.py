import urllib.request, re, sys
url = sys.argv[1] if len(sys.argv)>1 else 'https://www.tradingview.com/script/Uk4Hf7Od-Swing-High-Low-Wick-Zones-Support-Resistance-Indicator/'
req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
text = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='ignore')
# search
rfc = re.findall(r"[A-Za-z]{3},\s*\d{1,2}\s+\w{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+GMT", text)
iso = re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", text)
print('RFC matches (first 10):')
for m in rfc[:10]:
    print('  ', m)
print('\nISO matches (first 10):')
for m in iso[:10]:
    print('  ', m)
idx = text.find('Published:')
if idx != -1:
    print('\nSnippet around Published:\n', text[idx:idx+200])
else:
    print('\nNo "Published:" literal found in HTML')
# Also search for 'updated' token
upd = [(m.start(), text[m.start():m.start()+120]) for m in re.finditer('updated', text, flags=re.I)]
if upd:
    print('\nFound "updated" snippets (first 5):')
    for i,sn in upd[:5]:
        print('  at', i, sn)
else:
    print('\nNo "updated" keyword matches')

# Search for 'published' like tokens and show surrounding context
for k in ['published','published_at','created_at','datePublished','upload_time','date_published']:
    hits = [m.start() for m in re.finditer(k, text, flags=re.I)]
    if hits:
        print(f"\nFound token {k}, occurrences={len(hits)}")
        for pos in hits[:5]:
            print('  pos', pos, '->', text[pos-120:pos+120].replace('\n',' '))


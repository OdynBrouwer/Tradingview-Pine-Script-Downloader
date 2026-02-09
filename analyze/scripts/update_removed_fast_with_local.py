import json
from pathlib import Path

ROOT = Path('.').resolve()
REMOVED_FAST = ROOT / 'analyze' / 'jsons' / 'removed-fast.json'
LOCAL_MATCHES = ROOT / 'analyze' / 'jsons' / 'removed-local-matches.json'
OUT = ROOT / 'analyze' / 'jsons' / 'removed-fast-updated.json'

def main():
    rf = json.loads(REMOVED_FAST.read_text(encoding='utf-8'))
    lm = json.loads(LOCAL_MATCHES.read_text(encoding='utf-8'))
    # build map url -> first found path
    mapping = {}
    for item in lm.get('matches', []):
        try:
            url, title, found = item
        except Exception:
            continue
        if found:
            mapping[url] = found[0]

    updated = 0
    for entry in rf:
        url = entry.get('url')
        if url in mapping:
            entry['pine_path'] = mapping[url]
            entry['local_found'] = True
            # mark moved status if path contains '\\remove\\' (Windows) or '/remove/'
            p = mapping[url]
            if ('\\remove\\' in p) or ('/remove/' in p):
                entry['local_in_remove'] = True
            updated += 1
        else:
            entry.setdefault('local_found', False)

    OUT.write_text(json.dumps(rf, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Updated {updated} entries in {OUT}")

if __name__ == '__main__':
    main()

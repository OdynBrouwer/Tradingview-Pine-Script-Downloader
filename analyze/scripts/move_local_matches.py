import json
import shutil
from pathlib import Path
import datetime

ROOT = Path('.').resolve()
MATCH_FILE = ROOT / 'analyze' / 'jsons' / 'removed-local-matches.json'
OUT_FILE = ROOT / 'analyze' / 'jsons' / 'removed-moved.json'

def main():
    data = json.load(open(MATCH_FILE, encoding='utf-8'))
    matches = data.get('matches', [])
    moved = []
    errors = []
    for entry in matches:
        # entry expected: [url, title, [found_paths]]
        try:
            url, title, found = entry
        except Exception:
            errors.append({'entry': entry, 'error': 'invalid_entry'})
            continue
        for src in found:
            src_path = Path(src)
            if not src_path.exists():
                errors.append({'src': src, 'error': 'not_found'})
                continue
            dest_dir = src_path.parent / 'remove'
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src_path.name
            if dest.exists():
                stamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                dest = dest_dir / f"{src_path.stem}_{stamp}{src_path.suffix}"
            try:
                shutil.move(str(src_path), str(dest))
                moved.append({'src': str(src_path), 'dst': str(dest)})
            except Exception as e:
                errors.append({'src': str(src_path), 'error': str(e)})

    out = {
        'moved_count': len(moved),
        'errors_count': len(errors),
        'moved': moved,
        'errors': errors,
    }
    json.dump(out, open(OUT_FILE, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    print(f"Moved: {len(moved)} files; errors: {len(errors)}")
    print(f"Wrote {OUT_FILE}")

if __name__ == '__main__':
    main()

import shutil
from pathlib import Path
import json
import datetime

ROOT = Path('.').resolve()
DOWNLOADS = ROOT / 'pinescript_downloads'
OUT = ROOT / 'analyze' / 'jsons' / 'removed-moved-cleanup.json'

def main():
    moved = []
    errors = []
    # find all nested remove/remove directories
    for parent in DOWNLOADS.rglob('remove'):
        nested = parent / 'remove'
        if nested.exists() and nested.is_dir():
            for f in nested.iterdir():
                if f.is_file():
                    dest = parent / f.name
                    if dest.exists():
                        stamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                        dest = parent / f"{f.stem}_{stamp}{f.suffix}"
                    try:
                        shutil.move(str(f), str(dest))
                        moved.append({'src': str(f), 'dst': str(dest)})
                    except Exception as e:
                        errors.append({'src': str(f), 'error': str(e)})
            # if nested now empty, remove directory
            try:
                if not any(nested.iterdir()):
                    nested.rmdir()
            except Exception:
                pass

    out = {'moved_count': len(moved), 'errors_count': len(errors), 'moved': moved, 'errors': errors}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Moved {len(moved)} files from nested remove directories; errors: {len(errors)}")
    print(f"Wrote {OUT}")

if __name__ == '__main__':
    main()

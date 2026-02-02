import json
import subprocess
import sys
from pathlib import Path

# Gebruik: python download_from_json.py page-01/page-01-urls.json

def main():
    if len(sys.argv) < 2:
        print("Gebruik: python download_from_json.py <pad/naar/page-XX-urls.json>")
        sys.exit(1)
    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"Bestand niet gevonden: {json_path}")
        sys.exit(1)
    with open(json_path, encoding="utf-8") as f:
        urls = json.load(f)
    # Bepaal de pagemap uit het json-bestand
    page_dir = json_path.parent

    # Use per-URL downloads via tv_downloader_enhanced.py to ensure the visible browser and positional click are used
    page_dir = json_path.parent

    # Optional override: pass `--force` on the command-line to force redownloads
    force = '--force' in sys.argv

    skipped = 0
    succeeded = 0
    failed = 0

    for i, entry in enumerate(urls, 1):
        url = entry["url"] if isinstance(entry, dict) else entry

        # Derive script id from the URL (e.g., '59rIB01w' from '/script/59rIB01w-.../')
        last_part = url.rstrip('/').split('/')[-1]
        script_id = last_part.split('-')[0]

        # Check for existing files: <id>_*.pine or <id>.pine
        existing = any(page_dir.glob(f"{script_id}_*.pine")) or (page_dir / f"{script_id}.pine").exists()
        if existing and not force:
            print(f"\n[{i}/{len(urls)}] Skipping (exists): {url}  - matched script id: {script_id}")
            skipped += 1
            continue

        print(f"\n[{i}/{len(urls)}] Downloading: {url}")
        cmd = [
            sys.executable, "tv_downloader_enhanced.py",
            "--url", url,
            "--positional-click",
            "--visible",
            "--dump-copy-diagnostics",
            "--output", str(page_dir)
        ]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"   ✗ Fout bij downloaden: {url}")
            failed += 1
        else:
            print(f"   ✓ Gedownload: {url}")
            succeeded += 1

    # Summary
    print("\nBulk run summary:")
    print(f"  Succeeded: {succeeded}")
    print(f"  Skipped  : {skipped}")
    print(f"  Failed   : {failed}")

if __name__ == "__main__":
    main()


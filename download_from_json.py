import json
import subprocess
import sys
from pathlib import Path

# Gebruik: python download_from_json.py page-01/page-01-urls.json

# Optional: enable per-existing-script update checks (compare remote/local Published dates)
# Use --check-updates to enable this behavior
from tv_downloader_enhanced import EnhancedTVScraper

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
    # By default we check remote Published dates for existing scripts. Use `--no-check-updates` to disable.
    force = '--force' in sys.argv
    check_updates = '--no-check-updates' not in sys.argv

    skipped = 0
    succeeded = 0
    failed = 0

    # Initialize a lightweight scraper helper only if needed for update checks
    scraper = None
    if check_updates:
        try:
            scraper = EnhancedTVScraper(output_dir=str(page_dir))
        except Exception:
            scraper = None

    for i, entry in enumerate(urls, 1):
        url = entry["url"] if isinstance(entry, dict) else entry

        # Derive script id from the URL (e.g., '59rIB01w' from '/script/59rIB01w-.../')
        last_part = url.rstrip('/').split('/')[-1]
        script_id = last_part.split('-')[0]

        # Check for existing files: <id>_*.pine or <id>.pine
        existing = any(page_dir.glob(f"{script_id}_*.pine")) or (page_dir / f"{script_id}.pine").exists()
        if existing and not force:
            if check_updates and scraper:
                try:
                    print(f"\n[{i}/{len(urls)}] Existing: {url}  - checking remote Published date...")
                    local_p = scraper._find_local_file_for_url(url)
                    local_dt = scraper._parse_published_from_file(local_p) if local_p else None
                    remote_dt = scraper._fetch_remote_published(url)
                    print(f"   [check-updates] local={local_dt} remote={remote_dt}")

                    # Normalize by truncating microseconds and compare whole seconds deterministically
                    try:
                        is_updated = False
                        if remote_dt and local_dt:
                            remote_s = remote_dt.replace(microsecond=0)
                            local_s = local_dt.replace(microsecond=0)
                            delta = (remote_s - local_s).total_seconds()
                            print(f"   [check-updates] normalized_utc remote_s={remote_s} local_s={local_s} delta_seconds={delta:+.6f}")
                            is_updated = (remote_s > local_s)
                        elif remote_dt and (local_dt is None):
                            is_updated = True

                        if is_updated:
                            print(f"   [check-updates] Update detected: re-downloading {url} (remote={remote_s}, local={local_s}, delta={delta:+.6f}s)")
                        else:
                            print(f"   [check-updates] No update detected; skipping {url} (delta={delta:+.6f}s)" if remote_dt and local_dt else f"   [check-updates] No update detected; skipping {url}")
                            skipped += 1
                            continue
                    except Exception as e:
                        print(f"   [check-updates] Error normalizing/comparing dates for {url}: {e}")
                        skipped += 1
                        continue
                except Exception as e:
                    print(f"   [check-updates] Error checking updates for {url}: {e}")
                    # fallback to skip to avoid accidental re-downloads on error
                    skipped += 1
                    continue
            else:
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


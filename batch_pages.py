#!/usr/bin/env python3
"""batch_pages.py

Run `download_from_json.py` against many `pinescript_downloads/page-XX/page-XX-urls.json` files.
Example: python batch_pages.py --start 10 --end 20 --force
"""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description="Run download_from_json.py for a range of page folders (page-XX)")
    p.add_argument("--start", type=int, required=True, help="Start page number (e.g., 10)")
    p.add_argument("--end", type=int, required=True, help="End page number (inclusive, e.g., 20)")
    p.add_argument("--force", action="store_true", help="Force re-download even if .pine files exist")
    p.add_argument("--no-check-updates", action="store_true", help="Disable check of remote Published date when skipping existing scripts")
    p.add_argument("--suppress-diagnostics", action="store_true", help="Suppress diagnostic sidecar files (useful for scheduled runs)")
    p.add_argument("--positional-click", action="store_true", help="Use positional click mode for copy extraction (useful for headless/scheduled runs)")
    args = p.parse_args()

    missing = []
    succeeded = []
    failed = []

    for i in range(args.start, args.end + 1):
        n = f"{i:02d}"
        page_dir = Path(f"pinescript_downloads/page-{n}")
        base_dir = Path('pinescript_downloads')
        # Find JSON either in the old per-page layout or the new top-level per-type layout
        candidates = []
        # Old layout: pinescript_downloads/page-XX/page-XX-urls.json
        top = page_dir / f"page-{n}-urls.json"
        if top.exists():
            candidates.append(top)
        # Old layout: check for any type-specific subfolders under page-XX
        if page_dir.exists():
            for sub in page_dir.iterdir():
                if sub.is_dir():
                    p = sub / f"page-{n}-urls.json"
                    if p.exists():
                        candidates.append(p)
        # New layout: top-level per-type folders like pinescript_downloads/indicators/page-XX-urls.json
        for t in ('indicators', 'libraries', 'strategies'):
            p = base_dir / t / f"page-{n}-urls.json"
            if p.exists():
                candidates.append(p)

        if not candidates:
            print(f"Skipping page-{n}: no page json found in {page_dir}")
            missing.append(n)
            continue

        for json_path in candidates:
            print(f"\n[{n}] Processing: {json_path}")
            cmd = [sys.executable, "download_from_json.py", str(json_path)]
            if args.force:
                cmd.append("--force")
            # Default behavior: enable update checks unless user supplied --no-check-updates
            if not args.no_check_updates:
                cmd.append("--check-updates")
            if args.suppress_diagnostics:
                cmd.append("--suppress-diagnostics")
            if args.positional_click:
                cmd.append("--positional-click")

            res = subprocess.run(cmd)
            if res.returncode == 0:
                succeeded.append(str(json_path.parent.name))
            else:
                failed.append(str(json_path.parent.name))

    print("\nBatch pages summary:")
    print(f"  Processed (succeeded): {len(succeeded)} -> {', '.join(succeeded) if succeeded else '-' }")
    print(f"  Missing: {len(missing)} -> {', '.join(missing) if missing else '-' }")
    print(f"  Failed: {len(failed)} -> {', '.join(failed) if failed else '-' }")

    if failed:
        print("One or more pages failed. Exit code 1.")
        sys.exit(1)


if __name__ == '__main__':
    main()

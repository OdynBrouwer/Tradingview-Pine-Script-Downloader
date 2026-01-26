#!/usr/bin/env bash
set -euo pipefail

# NOTE: dependencies and Playwright browsers are installed at image build time.
# This entrypoint intentionally does NOT attempt to install system packages
# at runtime to avoid permission issues inside containers.

if [[ $# -eq 0 ]]; then
  echo "Usage: docker run --rm tv-downloader python tv_downloader_enhanced.py --url <URL> [--output ./pinescript_downloads]"
  echo "Or run: python scripts/verify_playwright.py to check browsers are available."
  exec /bin/bash
fi

# If first arg starts with '-' assume user passed script args
if [[ "$1" == -* ]]; then
  set -- python tv_downloader_enhanced.py "$@"
fi

exec "$@"

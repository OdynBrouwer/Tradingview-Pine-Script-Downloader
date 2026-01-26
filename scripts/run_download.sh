#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run the downloader with sensible defaults
# Usage: run_download.sh --url <URL> [--max-pages N] [--delay 2.0] [additional args]

PINE_OUTPUT_DIR="${PINE_OUTPUT_DIR:-/mnt/pinescripts}"

if [ ! -d "$PINE_OUTPUT_DIR" ]; then
  echo "Warning: PINE_OUTPUT_DIR '$PINE_OUTPUT_DIR' not found. Falling back to ./pinescript_downloads"
  PINE_OUTPUT_DIR="./pinescript_downloads"
  mkdir -p "$PINE_OUTPUT_DIR"
fi

# Activate venv if available
if [ -f ".venv/bin/activate" ]; then
  # shellcheck source=/dev/null
  . .venv/bin/activate
fi

# Ensure we forward args and set output
exec python tv_downloader_enhanced.py "$@" --output "$PINE_OUTPUT_DIR"

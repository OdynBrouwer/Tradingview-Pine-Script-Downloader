#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <URL> [max_pages]"
  exit 1
fi

URL="$1"
MAX_PAGES="${2:-5}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Activate venv if present
if [ -f .venv/bin/activate ]; then
  # shellcheck source=/dev/null
  . .venv/bin/activate
fi

# Prepare output dirs
rm -rf test_fixed test_enhanced
mkdir -p test_fixed test_enhanced

echo "Running fixed downloader..."
python tv_downloader_fixed.py --url "$URL" --output ./test_fixed --max-pages "$MAX_PAGES"

echo "Running enhanced downloader..."
python tv_downloader_enhanced.py --url "$URL" --output ./test_enhanced --no-resume --delay 2.0

# Collect results
find test_fixed -type f -name '*.pine' | sort > /tmp/fixed_files.txt || true
find test_enhanced -type f -name '*.pine' | sort > /tmp/enhanced_files.txt || true
fixed_count=$(wc -l < /tmp/fixed_files.txt || echo 0)
enhanced_count=$(wc -l < /tmp/enhanced_files.txt || echo 0)

echo "\nResults:"
echo "  Fixed downloader:    $fixed_count .pine files"
echo "  Enhanced downloader: $enhanced_count .pine files"

if [ "$fixed_count" -ne "$enhanced_count" ]; then
  echo "\nDifferences (paths):"
  echo "Files only in fixed:"
  comm -23 /tmp/fixed_files.txt /tmp/enhanced_files.txt || true
  echo "\nFiles only in enhanced:"
  comm -13 /tmp/fixed_files.txt /tmp/enhanced_files.txt || true
else
  echo "\nCounts match." 
fi

# Also print a short sample for manual inspection
echo "\nSample files (first 10):"
echo "  fixed:"
head -n 10 /tmp/fixed_files.txt || true
echo "  enhanced:"
head -n 10 /tmp/enhanced_files.txt || true

exit 0

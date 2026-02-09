# Archived scripts

This folder contains scripts that have been superseded or archived for historical/reference reasons. The files here are left for traceability and can be removed later if desired.

- `check_updates.py` (archived 2026-02-09): replaced by built-in update-detection in `download_from_json.py` / `batch_pages.py` (enabled by default). The built-in logic prefers JSON `created_at`/`published_at`, normalizes to UTC, and compares seconds (microseconds are ignored) to avoid spurious re-downloads.

If you rely on the standalone `check_updates.py` for a specific workflow, copy it from here and adapt it; otherwise it is safe to keep archived.

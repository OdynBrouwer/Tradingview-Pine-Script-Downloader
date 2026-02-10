# Archived scripts

This folder contains scripts that have been superseded or archived for historical/reference reasons. The files here are left for traceability and can be removed later if desired.

- `check_updates.py` (archived 2026-02-09): replaced by built-in update-detection in `download_from_json.py` / `batch_pages.py` (enabled by default). The built-in logic prefers JSON `created_at`/`published_at`, normalizes to UTC, and compares seconds (microseconds are ignored) to avoid spurious re-downloads.

Other archived scripts in this folder (kept for reference):
- `analyze_ids.py`
- `merge_retry3_into_categories.py`
- `merge_retry_into_categories.py`
- `run_failed_in_batches.py`
- `summarize_retry2.py`
- `test_pubdate.py` (diagnostic)
- `update_failed_from_retry2.py`

If you rely on any of these standalone helpers for a specific workflow, copy the file(s) and adapt locally; otherwise it is safe to keep them archived for traceability.

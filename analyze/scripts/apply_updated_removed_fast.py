import json, shutil, datetime
from pathlib import Path

ROOT = Path('.').resolve()
RF = ROOT / 'analyze' / 'jsons' / 'removed-fast.json'
UPDATED = ROOT / 'analyze' / 'jsons' / 'removed-fast-updated.json'
BACKUP_DIR = ROOT / 'analyze' / 'jsons' / 'backups'
OUT_URLS = ROOT / 'analyze' / 'jsons' / 'removed-fast-urls.txt'
SUMMARY = ROOT / 'analyze' / 'jsons' / 'removed-fast-apply-summary.json'

if not UPDATED.exists():
    print('No updated file found:', UPDATED)
    raise SystemExit(1)

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
backup_path = BACKUP_DIR / f'removed-fast.{now}.bak.json'
if RF.exists():
    shutil.copy2(RF, backup_path)
    print('Backed up', RF, 'to', backup_path)
else:
    print('No existing removed-fast.json to backup')

# Replace RF with UPDATED
shutil.move(str(UPDATED), str(RF))
print('Replaced', RF, 'with updated file')

# Regenerate removed-fast-urls.txt
j = json.loads(RF.read_text(encoding='utf-8'))
removed_urls = [e.get('url') for e in j if e.get('removed')]
with OUT_URLS.open('w', encoding='utf-8') as f:
    for u in removed_urls:
        f.write(u + '\n')

# counts
total = len(j)
removed_count = len(removed_urls)
local_found_count = sum(1 for e in j if e.get('local_found'))
local_in_remove_count = sum(1 for e in j if e.get('local_in_remove'))

summary = {
    'timestamp': now,
    'total_entries': total,
    'removed_count': removed_count,
    'local_found_count': local_found_count,
    'local_in_remove_count': local_in_remove_count,
    'backup': str(backup_path) if backup_path.exists() else None,
}
SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
print('Wrote summary:', SUMMARY)
print('Totals:', summary)

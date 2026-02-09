import json
from pathlib import Path
import subprocess

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

ROOT = Path(__file__).parent
OUT = ROOT / 'jsons'
OUT.mkdir(exist_ok=True)

in_path = OUT / 'failed-pubdates.json'
if not in_path.exists():
    raise SystemExit('Input failed-pubdates.json missing')

urls_data = json.loads(in_path.read_text(encoding='utf-8'))
# normalize to list of url strings
urls = [it['url'] if isinstance(it, dict) and 'url' in it else it for it in urls_data]

batch_size = 100  # smaller parts to avoid long-running single-process crashes
max_attempts = 2   # retry a failing batch once
parts = []
for idx, part in enumerate(chunk(urls, batch_size), start=1):
    tmp = OUT / f'tmp-failed-batch-{idx:04d}.json'
    out = OUT / f'failed-pubdates-part-{idx:04d}.json'

    # Skip batch if output already exists (resume support)
    if out.exists():
        print(f'Batch {idx} output {out.name} already exists, skipping')
        parts.append(out)
        continue

    tmp.write_text(json.dumps(part, indent=2), encoding='utf-8')

    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        print(f'Running batch {idx} (attempt {attempts}/{max_attempts}) ({len(part)} URLs) -> {out.name}')
        cmd = ['python', str(ROOT / 'scrape_pubdates.py'), '--input', str(tmp), '--output', str(out), '--delay', '1.0', '--concurrency', '1', '--jitter', '0', '--retries', '1']
        try:
            subprocess.run(cmd, check=True)
            break
        except subprocess.CalledProcessError as e:
            print(f'Batch {idx} failed on attempt {attempts}: {e}')
            if attempts >= max_attempts:
                print(f'Giving up on batch {idx} after {attempts} attempts; moving to next batch')
                break
    parts.append(out)
    try:
        tmp.unlink()
    except Exception:
        pass

# Merge
combined = []
for p in parts:
    if p.exists():
        combined.extend(json.loads(p.read_text(encoding='utf-8')))

out_all = OUT / 'failed-pubdates-retry3.json'
out_all.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding='utf-8')
print('Wrote', out_all)

# Summary counts
tot = len(combined)
ok = sum(1 for it in combined if it.get('published_utc'))
print('Total results', tot, 'with published_utc', ok)

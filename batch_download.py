#!/usr/bin/env python3
"""
Batch Download Script
=====================
Download Pine Scripts from multiple TradingView pages at once.

Usage:
    python batch_download.py urls.txt
    python batch_download.py --urls "https://..." "https://..."
"""

import argparse
import asyncio
import sys
import os
from pathlib import Path

# Import from the enhanced downloader (which is now fixed)
from tv_downloader_enhanced import EnhancedTVScraper


async def batch_download(urls: list[str], output_dir: str | None = None, 
                        delay: float = 2.0, max_pages: int = 10, resume: bool = False, debug_pages: bool = False, fast: bool = False, positional_click: bool = False):
    """Download from multiple URLs sequentially.

    resume: if True, skip scripts that already exist (default: False)
    debug_pages: enable per-page debugging output
    """
    # Resolve output_dir default if None
    if not output_dir:
        env_output = os.environ.get('PINE_OUTPUT_DIR')
        if env_output:
            output_dir = env_output
        elif os.path.exists('/mnt/pinescripts'):
            output_dir = '/mnt/pinescripts'
        else:
            output_dir = './pinescript_downloads'
    """Download from multiple URLs sequentially.

    visible: show browser window when downloading each page
    debug_pages: enable per-page debugging output
    """
    
    print(f"\n{'='*70}")
    print(f"  BATCH DOWNLOAD")
    print(f"  Processing {len(urls)} URLs")
    print(f"{'='*70}\n")
    
    total_stats = {
        'downloaded': 0,
        'skipped': 0,
        'failed': 0
    }
    import json
    import re
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] Processing: {url}\n")
        print("-" * 70)
        scraper = EnhancedTVScraper(
            output_dir=output_dir,
            headless=True,  # headless voor scraping
            positional_click=False
        )
        try:
            await scraper.setup()
            await scraper.page.goto(url, wait_until='networkidle', timeout=60000)
            await scraper.page.wait_for_timeout(1200)
            scripts = await scraper.get_scripts_from_listing(max_scroll_attempts=max_pages, debug_pages=debug_pages)
            page_id = None
            # Probeer page-XX uit de url te halen
            m = re.search(r'page-(\d+)', url)
            if m:
                page_id = f"page-{int(m.group(1)):02d}"
            else:
                page_id = f"page-{i:02d}"

            # Detect script_type in the query string (e.g., ?script_type=indicators)
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            script_type = None
            if 'script_type' in qs and qs['script_type']:
                script_type = qs['script_type'][0].lower()

            # If we detected a script_type, save directly under that top-level folder (e.g., ./indicators/page-01-urls.json)
            if script_type:
                page_dir = Path(output_dir) / script_type
            else:
                page_dir = Path(output_dir) / page_id
            page_dir.mkdir(parents=True, exist_ok=True)

            out_json = page_dir / f"{page_id}-urls.json"
            # Sla alleen de urls van deze pagina op
            urls_this_page = [{'url': s['url'], 'title': s.get('title', '')} for s in scripts] if scripts else []
            with open(out_json, 'w', encoding='utf-8') as f:
                json.dump(urls_this_page, f, indent=2, ensure_ascii=False)
            print(f"   Found {len(urls_this_page)} scripts on page. Saved to {out_json}")
        except Exception as e:
            print(f"Error processing {url}: {e}")
        finally:
            try:
                await scraper.cleanup()
            except Exception:
                pass
        if i < len(urls):
            print(f"\nWaiting before next URL...")
            await asyncio.sleep(2)
    print("\nKlaar met verzamelen van URLs per pagina. Je kunt nu per map downloaden.")
    return
    
    # Final summary
    print(f"\n{'='*70}")
    print(f"  BATCH DOWNLOAD COMPLETE")
    print(f"{'='*70}")
    print(f"  Total Downloaded:  {total_stats['downloaded']}")
    print(f"  Total Skipped:     {total_stats['skipped']}")
    print(f"  Total Failed:      {total_stats['failed']}")
    print(f"\n  Output: {output_dir}")
    print(f"{'='*70}\n")


def load_urls_from_file(filepath: str) -> list[str]:
    """Load URLs from a text file (one per line)."""
    urls = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and 'tradingview.com' in line:
                urls.append(line)
    return urls


async def main():
    parser = argparse.ArgumentParser(description='Batch download Pine Scripts from TradingView (of alleen URL scraping)')
    parser.add_argument(
        '--collect-urls-only',
        action='store_true',
        help='Verzamel alleen alle script-urls uit de listings en sla op in script_urls.json (geen downloads)'
    )
    
    parser.add_argument(
        'file',
        nargs='?',
        help='Text file with URLs (one per line)'
    )
    
    parser.add_argument(
        '--urls',
        nargs='+',
        help='URLs to download from'
    )
    
    # Default output: prefer env PINE_OUTPUT_DIR, else use /mnt/pinescripts if present, else local folder
    env_output = os.environ.get('PINE_OUTPUT_DIR')
    if env_output:
        default_output = env_output
    elif os.path.exists('/mnt/pinescripts'):
        default_output = '/mnt/pinescripts'
    else:
        default_output = './pinescript_downloads'

    parser.add_argument(
        '--output', '-o',
        default=default_output,
        help='Output directory (defaults to PINE_OUTPUT_DIR or /mnt/pinescripts when available)'
    )
    
    parser.add_argument(
        '--max-pages', '-p',
        type=int,
        default=10,
        help='Max pages per URL'
    )
    
    parser.add_argument(
        '--delay', '-d',
        type=float,
        default=2.0,
        help='Delay between requests'
    )

    # --visible option removed: always runs in visible mode for clipboard extraction
    parser.add_argument('--debug-pages', action='store_true', help='Verbose page visit logging (debug)')
    parser.add_argument('--fast', action='store_true', help='Faster mode: fewer retries and shorter waits (less reliable)')
    parser.add_argument('--positional-click', action='store_true', help='Use fixed-position click to trigger copy button (fast, fragile)')
    parser.add_argument('--template', help='URL template with {n} or {n:02d} placeholder, e.g. ".../page-{n}/?..."')
    parser.add_argument('--start', type=int, default=1, help='Start number for template generation')
    parser.add_argument('--end', type=int, help='End number (inclusive) for template generation')
    # Resume flags: default is NO resume (download everything). Use --resume to enable skipping of existing scripts.
    parser.add_argument('--resume', action='store_true', help='Enable resume (skip already existing scripts)')
    parser.add_argument('--no-resume', action='store_true', help='Explicitly disable resume (download all scripts even if files exist)')
    
    args = parser.parse_args()
    
    # Collect URLs
    urls = []
    
    if args.file:
        if Path(args.file).exists():
            urls.extend(load_urls_from_file(args.file))
        else:
            print(f"Error: File not found: {args.file}")
            sys.exit(1)
    
    if args.urls:
        urls.extend(args.urls)

    # If a template with an end is provided, generate the list of page URLs
    if args.template and args.end:
        generated = []
        for n in range(args.start, args.end + 1):
            try:
                generated.append(args.template.format(n=n))
            except Exception:
                # Fallback if user used simple {n} placeholder without format spec
                generated.append(args.template.replace('{n}', str(n)))
        urls = generated

    if not urls:
        print("Error: No URLs provided")
        print("Usage:")
        print("  python batch_download.py urls.txt")
        print("  python batch_download.py --urls 'https://...' 'https://...'")
        print("  or use --template and --start/--end to generate pages")
        sys.exit(1)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    
    # Determine effective resume behavior: --resume wins, otherwise default is no-resume
    effective_resume = True if args.resume else False

    if args.collect_urls_only:
        await batch_download(
            urls=unique_urls,
            output_dir=args.output,
            delay=args.delay,
            max_pages=args.max_pages,
            resume=False,
            debug_pages=args.debug_pages,
            fast=True,
            positional_click=False
        )
        return
    else:
        await batch_download(
            urls=unique_urls,
            output_dir=args.output,
            delay=args.delay,
            max_pages=args.max_pages,
            resume=effective_resume,
            debug_pages=args.debug_pages,
            fast=args.fast,
            positional_click=args.positional_click
        )


if __name__ == '__main__':
    asyncio.run(main())

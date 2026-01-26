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
from pathlib import Path

# Import from the enhanced downloader (which is now fixed)
from tv_downloader_enhanced import EnhancedTVScraper


async def batch_download(urls: list[str], output_dir: str = "./pinescript_downloads", 
                        delay: float = 2.0, max_pages: int = 10, visible: bool = False, debug_pages: bool = False):
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
    
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] Processing: {url}\n")
        print("-" * 70)
        
        scraper = EnhancedTVScraper(
            output_dir=output_dir,
            headless=not visible
        )
        
        try:
            await scraper.download_all(
                base_url=url,
                max_pages=max_pages,
                delay=delay,
                resume=True,
                debug_pages=debug_pages
            )
            
            total_stats['downloaded'] += scraper.stats['downloaded']
            total_stats['skipped'] += scraper.stats['skipped_protected'] + scraper.stats['skipped_no_code']
            total_stats['failed'] += scraper.stats['failed']
            
        except Exception as e:
            print(f"Error processing {url}: {e}")
            total_stats['failed'] += 1
        
        # Extra delay between different sources
        if i < len(urls):
            print(f"\nWaiting before next URL...")
            await asyncio.sleep(5)
    
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
    parser = argparse.ArgumentParser(description='Batch download Pine Scripts from TradingView')
    
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
    
    parser.add_argument(
        '--output', '-o',
        default='./pinescript_downloads',
        help='Output directory'
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

    parser.add_argument('--visible', action='store_true', help='Show browser window')
    parser.add_argument('--debug-pages', action='store_true', help='Verbose page visit logging (debug)')
    parser.add_argument('--template', help='URL template with {n} or {n:02d} placeholder, e.g. ".../page-{n}/?..."')
    parser.add_argument('--start', type=int, default=1, help='Start number for template generation')
    parser.add_argument('--end', type=int, help='End number (inclusive) for template generation')
    
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
    
    await batch_download(
        urls=unique_urls,
        output_dir=args.output,
        delay=args.delay,
        max_pages=args.max_pages,
        visible=args.visible,
        debug_pages=args.debug_pages
    )


if __name__ == '__main__':
    asyncio.run(main())

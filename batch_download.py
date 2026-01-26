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
                        delay: float = 2.0, max_pages: int = 10):
    """Download from multiple URLs sequentially."""
    
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
            headless=True
        )
        
        try:
            await scraper.download_all(
                base_url=url,
                max_pages=max_pages,
                delay=delay,
                resume=True
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
    
    if not urls:
        print("Error: No URLs provided")
        print("Usage:")
        print("  python batch_download.py urls.txt")
        print("  python batch_download.py --urls 'https://...' 'https://...'")
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
        max_pages=args.max_pages
    )


if __name__ == '__main__':
    asyncio.run(main())

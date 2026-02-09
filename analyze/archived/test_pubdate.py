#!/usr/bin/env python3
"""Test script to specifically test the exact publish date extraction."""

import asyncio
from tv_downloader_enhanced import EnhancedTVScraper

async def test_publish_date():
    scraper = EnhancedTVScraper(output_dir='./pinescript_downloads/indicators', headless=False)
    await scraper.setup()
    
    try:
        url = "https://www.tradingview.com/script/uBlhqfGE/"
        print(f"Testing publish date extraction for: {url}")
        
        # Navigate to the page
        await scraper.page.goto(url, wait_until='networkidle', timeout=60000)
        await scraper.page.wait_for_timeout(2000)
        
        # Test the exact publish date extraction method
        exact_date = await scraper.extract_exact_publish_date()
        print(f"Exact publish date: {exact_date}")
        
        # Also test the full extraction
        result = await scraper.extract_pine_source(url)
        print(f"Full result published_date: {result.get('published_date')}")
        
    finally:
        await scraper.cleanup()

if __name__ == "__main__":
    asyncio.run(test_publish_date())
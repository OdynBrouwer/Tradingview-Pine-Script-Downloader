#!/usr/bin/env python3
"""
TradingView Pine Script Downloader
==================================
Automates downloading open-source Pine Script indicators/strategies from TradingView.

Usage:
    python tv_pinescript_downloader.py --url "https://www.tradingview.com/scripts/luxalgo/"
    python tv_pinescript_downloader.py --url "https://www.tradingview.com/scripts/luxalgo/" --max-pages 3
    python tv_pinescript_downloader.py --url "https://www.tradingview.com/scripts/luxalgo/" --output "./my_scripts"

Requirements:
    pip install playwright
    playwright install chromium
"""

import argparse
import asyncio
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


def sanitize_filename(name: str) -> str:
    """Convert a string to a valid filename."""
    # Remove or replace invalid characters
    name = re.sub(r'[<>:"/\\|?*\[\]]', '', name)
    name = re.sub(r'\s+', '_', name)
    name = name.strip('._')
    # Limit length
    if len(name) > 200:
        name = name[:200]
    return name or "unnamed_script"


def extract_script_id(url: str) -> str:
    """Extract script ID from TradingView URL."""
    # URL format: https://www.tradingview.com/script/ABC123-Script-Name/
    match = re.search(r'/script/([^-/]+)', url)
    return match.group(1) if match else ""


def extract_script_name(url: str) -> str:
    """Extract script name from TradingView URL."""
    # URL format: https://www.tradingview.com/script/ABC123-Script-Name/
    match = re.search(r'/script/[^-/]+-(.+?)/?$', url)
    if match:
        return match.group(1).replace('-', ' ')
    return ""


class TradingViewScraper:
    def __init__(self, output_dir: str = "./pinescript_downloads", headless: bool = True):
        self.output_dir = Path(output_dir)
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
        self.downloaded_count = 0
        self.failed_scripts = []
        self.skipped_scripts = []
        
    async def setup(self):
        """Initialize the browser."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=['--disable-blink-features=AutomationControlled']
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        self.page = await self.context.new_page()
        
    async def cleanup(self):
        """Close browser and cleanup."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def get_script_links_from_page(self) -> list[dict]:
        """Extract all script links from the current page."""
        scripts = await self.page.evaluate('''() => {
            const scripts = [];
            const articles = document.querySelectorAll('article');
            
            articles.forEach(article => {
                // Get the first link with /script/ in it (the title link)
                const titleLink = article.querySelector('a[href*="/script/"]');
                if (titleLink) {
                    const href = titleLink.href;
                    const title = titleLink.textContent?.trim() || '';
                    
                    // Check if it's marked as open-source (has Pine Script indicator badge)
                    const isPineScript = article.querySelector('[class*="Pine"]') !== null ||
                                        article.textContent?.includes('Pine Script');
                    
                    // Avoid duplicates by checking href
                    if (href && !scripts.some(s => s.url === href)) {
                        scripts.push({
                            url: href,
                            title: title,
                            isPineScript: isPineScript
                        });
                    }
                }
            });
            
            return scripts;
        }''')
        return scripts

    async def click_load_more(self) -> bool:
        """Click 'Show more' button if available. Returns True if clicked."""
        try:
            # Look for the "Show more publications" button
            show_more_btn = self.page.locator('button:has-text("Show more")')
            if await show_more_btn.count() > 0:
                await show_more_btn.first.click()
                await self.page.wait_for_timeout(2000)  # Wait for content to load
                return True
        except Exception:
            pass
        return False

    async def collect_all_scripts(self, base_url: str, max_pages: int = 10) -> list[dict]:
        """Collect all script links from a listing page, handling pagination."""
        print(f"\n📋 Collecting scripts from: {base_url}")
        
        await self.page.goto(base_url, wait_until='networkidle', timeout=60000)
        await self.page.wait_for_timeout(3000)
        
        all_scripts = []
        page_num = 1
        
        while page_num <= max_pages:
            print(f"   📄 Scanning page {page_num}...")
            
            # Get scripts from current view
            scripts = await self.get_script_links_from_page()
            new_scripts = [s for s in scripts if s['url'] not in [x['url'] for x in all_scripts]]
            all_scripts.extend(new_scripts)
            
            print(f"      Found {len(new_scripts)} new scripts (Total: {len(all_scripts)})")
            
            # Try to load more
            if not await self.click_load_more():
                print("   ✓ Reached end of list")
                break
                
            page_num += 1
            await self.page.wait_for_timeout(1500)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_scripts = []
        for s in all_scripts:
            if s['url'] not in seen:
                seen.add(s['url'])
                unique_scripts.append(s)
        
        print(f"\n✓ Collected {len(unique_scripts)} unique scripts")
        return unique_scripts

    async def extract_source_code(self, script_url: str) -> tuple[str, str, bool]:
        """
        Navigate to a script page and extract the Pine Script source code.
        Returns: (source_code, script_name, is_open_source)
        """
        script_name = extract_script_name(script_url)
        
        try:
            await self.page.goto(script_url, wait_until='domcontentloaded', timeout=60000)
            await self.page.wait_for_timeout(3000)
            
            # Get the actual script title from the page
            title_element = await self.page.query_selector('h1')
            if title_element:
                script_name = await title_element.text_content()
                script_name = script_name.strip() if script_name else script_name
            
            # Check if open-source (FIXED: look for explicit open-source indicator)
            script_type = await self.page.evaluate('''() => {
                const pageText = document.body.innerText;
                const pageUpper = pageText.toUpperCase();
                
                // Check for explicit OPEN-SOURCE indicator
                const isOpenSource = pageUpper.includes('OPEN-SOURCE SCRIPT') || 
                                    pageUpper.includes('OPEN-SOURCE') ||
                                    pageText.includes('Open-source script');
                
                // Check for invite-only or protected
                const isInviteOnly = pageText.toLowerCase().includes('invite-only');
                const isProtected = pageText.toLowerCase().includes('protected script');
                
                return {
                    isOpenSource: isOpenSource && !isInviteOnly && !isProtected,
                    isInviteOnly,
                    isProtected
                };
            }''')
            
            if not script_type['isOpenSource']:
                return "", script_name, False
            
            # Look for and click the "Source code" tab
            source_tab_selectors = [
                '[role="tab"]:has-text("Source code")',
                'button:has-text("Source code")',
                'div:has-text("Source code"):not(:has(*))',
            ]
            
            source_tab = None
            for selector in source_tab_selectors:
                try:
                    tab = self.page.locator(selector)
                    if await tab.count() > 0:
                        source_tab = tab.first
                        break
                except Exception:
                    continue
            
            if source_tab:
                await source_tab.click()
                await self.page.wait_for_timeout(2500)
            
            # FIXED: Extract source code by finding div container with many children
            source_code = await self.page.evaluate('''() => {
                // Find all divs and look for containers with many child divs (line-by-line code)
                const allDivs = document.querySelectorAll('div');
                
                for (const container of allDivs) {
                    const children = Array.from(container.children);
                    
                    // If this div has many child divs (50+), it might be the code container
                    if (children.length > 50) {
                        const texts = children.map(c => c.textContent?.trim() || '');
                        const joined = texts.join('\\n');
                        
                        // Check if this looks like Pine Script
                        if (joined.includes('//@version') && 
                            (joined.includes('indicator(') || joined.includes('strategy('))) {
                            // Filter out line numbers (pure numeric lines)
                            const codeLines = texts.filter(t => t && !/^\\d+$/.test(t));
                            return codeLines.join('\\n');
                        }
                    }
                }
                
                // Fallback: Look for pre/code elements
                const codeElements = document.querySelectorAll('pre code, pre');
                for (const elem of codeElements) {
                    const text = elem.textContent || '';
                    if (text.includes('//@version') && text.length > 200) {
                        return text;
                    }
                }
                
                return null;
            }''')
            
            return source_code or "", script_name, bool(source_code)
            
        except PlaywrightTimeoutError:
            print(f"      ⚠️ Timeout loading {script_url}")
            return "", script_name, False
        except Exception as e:
            print(f"      ⚠️ Error extracting source: {str(e)[:50]}")
            return "", script_name, False

    def save_script(self, source_code: str, script_name: str, script_id: str, category: str):
        """Save the Pine Script source code to a file."""
        # Create category subdirectory
        category_dir = self.output_dir / sanitize_filename(category)
        category_dir.mkdir(parents=True, exist_ok=True)
        
        # Create filename
        safe_name = sanitize_filename(script_name)
        filename = f"{script_id}_{safe_name}.pine"
        filepath = category_dir / filename
        
        # Save the file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"// Script: {script_name}\n")
            f.write(f"// ID: {script_id}\n")
            f.write(f"// Downloaded: {datetime.now().isoformat()}\n")
            f.write(f"// Source: TradingView\n")
            f.write("//\n\n")
            f.write(source_code)
        
        return filepath

    async def download_scripts(self, base_url: str, max_pages: int = 10, delay: float = 2.0):
        """Main method to download all scripts from a listing page."""
        # Determine category from URL
        parsed = urlparse(base_url)
        path_parts = [p for p in parsed.path.split('/') if p]
        category = path_parts[-1] if path_parts else "scripts"
        
        print(f"\n{'='*60}")
        print(f"TradingView Pine Script Downloader")
        print(f"{'='*60}")
        print(f"Source URL: {base_url}")
        print(f"Category: {category}")
        print(f"Output Directory: {self.output_dir}")
        print(f"Max Pages to Scan: {max_pages}")
        print(f"{'='*60}\n")
        
        await self.setup()
        
        try:
            # Collect all script URLs
            scripts = await self.collect_all_scripts(base_url, max_pages)
            
            if not scripts:
                print("❌ No scripts found!")
                return
            
            # Create output directory
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            # Download each script
            print(f"\n{'='*60}")
            print(f"Downloading {len(scripts)} scripts...")
            print(f"{'='*60}\n")
            
            for i, script_info in enumerate(scripts, 1):
                url = script_info['url']
                title = script_info.get('title', 'Unknown')
                script_id = extract_script_id(url)
                
                print(f"[{i}/{len(scripts)}] {title[:50]}...")
                
                # Extract source code
                source_code, script_name, is_open_source = await self.extract_source_code(url)
                
                if source_code:
                    filepath = self.save_script(source_code, script_name, script_id, category)
                    print(f"         ✓ Saved: {filepath.name}")
                    self.downloaded_count += 1
                elif not is_open_source:
                    print(f"         ⊘ Skipped (closed source/protected)")
                    self.skipped_scripts.append({'url': url, 'title': title, 'reason': 'closed source'})
                else:
                    print(f"         ✗ Failed to extract source code")
                    self.failed_scripts.append({'url': url, 'title': title})
                
                # Delay between requests
                if i < len(scripts):
                    await self.page.wait_for_timeout(int(delay * 1000))
            
            # Print summary
            self.print_summary(category)
            
        finally:
            await self.cleanup()

    def print_summary(self, category: str):
        """Print download summary."""
        print(f"\n{'='*60}")
        print("DOWNLOAD SUMMARY")
        print(f"{'='*60}")
        print(f"✓ Downloaded: {self.downloaded_count} scripts")
        print(f"⊘ Skipped (protected): {len(self.skipped_scripts)} scripts")
        print(f"✗ Failed: {len(self.failed_scripts)} scripts")
        print(f"\nOutput directory: {self.output_dir / sanitize_filename(category)}")
        
        if self.failed_scripts:
            print(f"\nFailed scripts:")
            for script in self.failed_scripts[:10]:
                print(f"  - {script['title'][:50]}")
            if len(self.failed_scripts) > 10:
                print(f"  ... and {len(self.failed_scripts) - 10} more")
        
        # Save manifest
        manifest_path = self.output_dir / sanitize_filename(category) / "manifest.txt"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            f.write(f"Download Summary\n")
            f.write(f"================\n")
            f.write(f"Date: {datetime.now().isoformat()}\n")
            f.write(f"Category: {category}\n")
            f.write(f"Downloaded: {self.downloaded_count}\n")
            f.write(f"Skipped: {len(self.skipped_scripts)}\n")
            f.write(f"Failed: {len(self.failed_scripts)}\n")
            f.write(f"\n--- Failed Scripts ---\n")
            for s in self.failed_scripts:
                f.write(f"{s['url']}\n")
            f.write(f"\n--- Skipped Scripts (Protected) ---\n")
            for s in self.skipped_scripts:
                f.write(f"{s['url']}\n")
        
        print(f"\nManifest saved: {manifest_path}")
        print(f"{'='*60}\n")


async def main():
    parser = argparse.ArgumentParser(
        description='Download Pine Script indicators from TradingView',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python tv_pinescript_downloader.py --url "https://www.tradingview.com/scripts/luxalgo/"
  python tv_pinescript_downloader.py --url "https://www.tradingview.com/scripts/luxalgo/" --max-pages 5
  python tv_pinescript_downloader.py --url "https://www.tradingview.com/scripts/editors-picks/" --output ./picks
  
Notes:
  - Only open-source scripts can be downloaded (protected/invite-only scripts are skipped)
  - Be respectful of TradingView's servers - use reasonable delays
  - Downloaded scripts retain their original licensing terms
        '''
    )
    
    parser.add_argument(
        '--url', '-u',
        required=True,
        help='TradingView scripts listing URL (e.g., https://www.tradingview.com/scripts/luxalgo/)'
    )
    
    parser.add_argument(
        '--output', '-o',
        default='./pinescript_downloads',
        help='Output directory for downloaded scripts (default: ./pinescript_downloads)'
    )
    
    parser.add_argument(
        '--max-pages', '-p',
        type=int,
        default=10,
        help='Maximum number of pages to scan (default: 10)'
    )
    
    parser.add_argument(
        '--delay', '-d',
        type=float,
        default=2.0,
        help='Delay between downloads in seconds (default: 2.0)'
    )
    
    parser.add_argument(
        '--headless',
        action='store_true',
        default=True,
        help='Run browser in headless mode (default: True)'
    )
    
    parser.add_argument(
        '--visible',
        action='store_true',
        help='Run with visible browser window (for debugging)'
    )
    
    args = parser.parse_args()
    
    # Validate URL
    if 'tradingview.com' not in args.url:
        print("Error: URL must be a TradingView URL")
        sys.exit(1)
    
    headless = not args.visible
    
    scraper = TradingViewScraper(
        output_dir=args.output,
        headless=headless
    )
    
    await scraper.download_scripts(
        base_url=args.url,
        max_pages=args.max_pages,
        delay=args.delay
    )


if __name__ == '__main__':
    asyncio.run(main())

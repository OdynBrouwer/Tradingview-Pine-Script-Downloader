#!/usr/bin/env python3
"""
TradingView Pine Script Downloader (Fixed Version)
===================================================
Correctly extracts open-source Pine Script indicators from TradingView.

Key fixes:
- Proper open-source detection (looks for "OPEN-SOURCE SCRIPT" text, not lock icons)
- Correct source code extraction from div elements
- Better tab clicking

Usage:
    python tv_downloader_fixed.py --url "https://www.tradingview.com/scripts/luxalgo/"
"""

import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


def sanitize_filename(name: str) -> str:
    """Convert a string to a valid filename."""
    name = re.sub(r'[<>:"/\\|?*\[\]]', '', name)
    name = re.sub(r'\s+', '_', name)
    name = name.strip('._')
    return name[:200] if len(name) > 200 else name or "unnamed_script"


def extract_script_id(url: str) -> str:
    """Extract script ID from TradingView URL."""
    match = re.search(r'/script/([^-/]+)', url)
    return match.group(1) if match else ""


class TVPineScriptDownloader:
    def __init__(self, output_dir: str | None = None, headless: bool = True):
        if output_dir:
            resolved = output_dir
        else:
            env_output = os.environ.get('PINE_OUTPUT_DIR')
            if env_output:
                resolved = env_output
            elif os.path.exists('/mnt/pinescripts'):
                resolved = '/mnt/pinescripts'
            else:
                resolved = './pinescript_downloads'
        self.output_dir = Path(resolved)
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
        self.stats = {
            'downloaded': 0,
            'skipped_protected': 0,
            'skipped_no_code': 0,
            'failed': 0
        }
        self.results = []
        
    async def setup(self):
        """Initialize browser."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        self.page = await self.context.new_page()
        
    async def cleanup(self):
        """Close browser."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def collect_scripts(self, base_url: str, max_clicks: int = 30) -> list[dict]:
        """Collect all script links by clicking 'Show more'."""
        print(f"📋 Collecting scripts from: {base_url}")
        
        await self.page.goto(base_url, wait_until='networkidle', timeout=60000)
        await self.page.wait_for_timeout(3000)
        
        scripts = {}
        click_count = 0
        
        while click_count < max_clicks:
            # Get current scripts
            current = await self.page.evaluate('''() => {
                const scripts = [];
                const links = document.querySelectorAll('a[href*="/script/"]');
                links.forEach(link => {
                    const href = link.href;
                    if (href && href.match(/\\/script\\/[a-zA-Z0-9]+-.+\\/?$/)) {
                        const title = link.textContent?.trim();
                        if (title && title.length > 3) {
                            scripts.push({ url: href, title: title.substring(0, 200) });
                        }
                    }
                });
                return scripts;
            }''')
            
            # Add new scripts
            prev_count = len(scripts)
            for s in current:
                if s['url'] not in scripts:
                    scripts[s['url']] = s
            
            print(f"   Found {len(scripts)} scripts...", end='\r')
            
            # If no new scripts, try clicking show more
            if len(scripts) == prev_count:
                try:
                    show_more = self.page.locator('button:has-text("Show more")')
                    if await show_more.count() > 0 and await show_more.first.is_visible():
                        await show_more.first.click()
                        await self.page.wait_for_timeout(2000)
                        click_count += 1
                    else:
                        break
                except:
                    break
            else:
                click_count = 0  # Reset if we found new scripts
                
            await self.page.wait_for_timeout(500)
        
        print(f"\n✓ Found {len(scripts)} unique scripts")
        return list(scripts.values())

    async def extract_script(self, script_url: str) -> dict:
        """Extract Pine Script source code from a script page."""
        result = {
            'url': script_url,
            'script_id': extract_script_id(script_url),
            'title': '',
            'author': '',
            'source_code': '',
            'version': '',
            'is_open_source': False,
            'error': None
        }
        
        try:
            await self.page.goto(script_url, wait_until='domcontentloaded', timeout=45000)
            await self.page.wait_for_timeout(3000)
            
            # Extract metadata and check if open-source
            metadata = await self.page.evaluate('''() => {
                const pageText = document.body.innerText;
                const pageUpper = pageText.toUpperCase();
                
                // Get title
                const h1 = document.querySelector('h1');
                const title = h1 ? h1.textContent.trim() : '';
                
                // Get author
                const authorLink = document.querySelector('a[href^="/u/"]');
                const author = authorLink ? authorLink.textContent.replace('by ', '').trim() : '';
                
                // Check for OPEN-SOURCE indicator (this is the key fix!)
                const isOpenSource = pageUpper.includes('OPEN-SOURCE SCRIPT') || 
                                    pageUpper.includes('OPEN-SOURCE') ||
                                    pageText.includes('Open-source script');
                
                // Check for invite-only or protected (these override open-source)
                const isInviteOnly = pageText.toLowerCase().includes('invite-only');
                const isProtected = pageText.toLowerCase().includes('protected script');
                
                return {
                    title,
                    author,
                    isOpenSource: isOpenSource && !isInviteOnly && !isProtected,
                    isInviteOnly,
                    isProtected
                };
            }''')
            
            result['title'] = metadata['title']
            result['author'] = metadata['author']
            result['is_open_source'] = metadata['isOpenSource']
            
            if not metadata['isOpenSource']:
                if metadata['isInviteOnly']:
                    result['error'] = 'invite-only'
                elif metadata['isProtected']:
                    result['error'] = 'protected'
                else:
                    result['error'] = 'not open-source'
                return result
            
            # Click on Source code tab
            try:
                source_tab = self.page.locator('[role="tab"]:has-text("Source code")')
                if await source_tab.count() > 0:
                    await source_tab.first.click()
                    await self.page.wait_for_timeout(2500)
            except Exception as e:
                result['error'] = f'Could not click source tab: {str(e)[:50]}'
                return result
            
            # Extract source code - the code is in individual div elements
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
                const codeElements = document.querySelectorAll('pre, code');
                for (const elem of codeElements) {
                    const text = elem.textContent || '';
                    if (text.includes('//@version') && text.length > 200) {
                        return text;
                    }
                }
                
                return null;
            }''')
            
            if source_code:
                # Clean up the code (remove line numbers if present)
                lines = source_code.split('\n')
                cleaned_lines = []
                for line in lines:
                    # Remove leading line numbers
                    clean_line = re.sub(r'^\d+\s*', '', line)
                    cleaned_lines.append(clean_line)
                
                result['source_code'] = '\n'.join(cleaned_lines)
                
                # Extract version
                version_match = re.search(r'//@version=(\d+)', result['source_code'])
                result['version'] = version_match.group(1) if version_match else ''
            else:
                result['error'] = 'Could not extract source code'
            
            return result
            
        except PlaywrightTimeoutError:
            result['error'] = 'Timeout'
            return result
        except Exception as e:
            result['error'] = str(e)[:100]
            return result

    def save_script(self, result: dict, category: str) -> Path:
        """Save Pine Script to file."""
        category_dir = self.output_dir / sanitize_filename(category)
        category_dir.mkdir(parents=True, exist_ok=True)
        
        safe_title = sanitize_filename(result['title'] or 'unknown')
        filename = f"{result['script_id']}_{safe_title}.pine"
        filepath = category_dir / filename
        
        header = [
            f"// Title: {result['title']}",
            f"// Author: {result['author']}",
            f"// Script ID: {result['script_id']}",
            f"// URL: {result['url']}",
            f"// Downloaded: {datetime.now().isoformat()}",
            f"// Pine Version: {result['version']}",
            "//",
            ""
        ]
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(header))
            f.write(result['source_code'])
        
        return filepath

    async def download_all(self, base_url: str, max_pages: int = 30, delay: float = 2.0):
        """Main download method."""
        parsed = urlparse(base_url)
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]
        category = path_parts[-1] if path_parts else "scripts"
        
        print(f"\n{'='*70}")
        print(f"  TradingView Pine Script Downloader (Fixed)")
        print(f"{'='*70}")
        print(f"  URL: {base_url}")
        print(f"  Category: {category}")
        print(f"  Output: {self.output_dir}")
        print(f"{'='*70}\n")
        
        await self.setup()
        
        try:
            # Collect scripts
            scripts = await self.collect_scripts(base_url, max_pages)
            
            if not scripts:
                print("❌ No scripts found!")
                return
            
            # Download each script
            print(f"\n{'='*70}")
            print(f"  Downloading {len(scripts)} scripts...")
            print(f"{'='*70}\n")
            
            for i, script_info in enumerate(scripts, 1):
                url = script_info['url']
                title = script_info.get('title', 'Unknown')[:50]
                
                print(f"[{i}/{len(scripts)}] {title}...")
                
                result = await self.extract_script(url)
                self.results.append(result)
                
                if result['source_code']:
                    filepath = self.save_script(result, category)
                    print(f"         ✓ Saved: {filepath.name[:60]}")
                    self.stats['downloaded'] += 1
                elif result['error'] in ['invite-only', 'protected', 'not open-source']:
                    print(f"         ⊘ Skipped: {result['error']}")
                    self.stats['skipped_protected'] += 1
                else:
                    print(f"         ✗ Failed: {result['error']}")
                    self.stats['failed'] += 1
                
                if i < len(scripts):
                    await self.page.wait_for_timeout(int(delay * 1000))
            
            # Save metadata
            self._save_metadata(category)
            
            # Print summary
            self._print_summary(category)
            
        finally:
            await self.cleanup()

    def _save_metadata(self, category: str):
        """Save metadata to JSON."""
        category_dir = self.output_dir / sanitize_filename(category)
        category_dir.mkdir(parents=True, exist_ok=True)
        
        metadata = {
            'download_date': datetime.now().isoformat(),
            'category': category,
            'stats': self.stats,
            'scripts': [{
                'script_id': r['script_id'],
                'title': r['title'],
                'author': r['author'],
                'url': r['url'],
                'version': r['version'],
                'is_open_source': r['is_open_source'],
                'downloaded': bool(r['source_code']),
                'error': r['error']
            } for r in self.results]
        }
        
        with open(category_dir / 'metadata.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def _print_summary(self, category: str):
        """Print summary."""
        print(f"\n{'='*70}")
        print(f"  SUMMARY")
        print(f"{'='*70}")
        print(f"  ✓ Downloaded:          {self.stats['downloaded']}")
        print(f"  ⊘ Protected/Private:   {self.stats['skipped_protected']}")
        print(f"  ✗ Failed:              {self.stats['failed']}")
        print(f"\n  Output: {self.output_dir / sanitize_filename(category)}")
        print(f"{'='*70}\n")


async def main():
    parser = argparse.ArgumentParser(description='Download Pine Scripts from TradingView')
    parser.add_argument('--url', '-u', required=True, help='TradingView scripts URL')
    # Default output: prefer env PINE_OUTPUT_DIR, else /mnt/pinescripts if present, else local folder
    env_output = os.environ.get('PINE_OUTPUT_DIR')
    if env_output:
        default_output = env_output
    elif os.path.exists('/mnt/pinescripts'):
        default_output = '/mnt/pinescripts'
    else:
        default_output = './pinescript_downloads'

    parser.add_argument('--output', '-o', default=default_output, help='Output directory')
    parser.add_argument('--max-pages', '-p', type=int, default=30, help='Max show-more clicks')
    parser.add_argument('--delay', '-d', type=float, default=2.0, help='Delay between downloads')
    parser.add_argument('--visible', action='store_true', help='Show browser window')
    
    args = parser.parse_args()
    
    downloader = TVPineScriptDownloader(
        output_dir=args.output,
        headless=not args.visible
    )
    
    await downloader.download_all(
        base_url=args.url,
        max_pages=args.max_pages,
        delay=args.delay
    )


if __name__ == '__main__':
    asyncio.run(main())

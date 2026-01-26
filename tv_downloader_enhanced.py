#!/usr/bin/env python3
"""
TradingView Pine Script Downloader (Enhanced Version)
======================================================
More robust source code extraction with multiple fallback methods.

This version includes:
- Multiple extraction strategies
- Better error handling
- Cookie consent handling
- Progress saving/resuming
- JSON export of metadata
"""

import argparse
import asyncio
import json
import os
import random
import re
import sys
import codecs
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# User agent pool for rotation (common browsers)
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
]


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


class EnhancedTVScraper:
    def __init__(self, output_dir: str | None = None, headless: bool = False):
        # Resolve default output: prefer env PINE_OUTPUT_DIR, then /mnt/pinescripts, otherwise ./pinescript_downloads
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
        self.headless = headless  # Respect headless parameter (use --visible to show)
        self.browser = None
        self.context = None
        self.page = None
        self.stats = {
            'downloaded': 0,
            'skipped_protected': 0,
            'skipped_no_code': 0,
            'failed': 0,
            'total': 0
        }
        self.results = []
        self.progress_file = None
        # Anti-detection state
        self.consecutive_failures = 0
        self.base_delay = 2.0  # Base delay in seconds
        self.current_user_agent = random.choice(USER_AGENTS)
        # Directories to ignore when scanning existing files (comma-separated env var)
        ignore_env = os.environ.get('PINE_IGNORE_DIRS', '@Recycle,@Recently-Snapshot')
        self.ignore_dir_prefixes = set([s.strip() for s in ignore_env.split(',') if s.strip()])

        
    async def setup(self):
        """Initialize the browser with anti-detection settings."""
        self.playwright = await async_playwright().start()
        print(f"[setup] launching browser; headless={self.headless} user_agent={self.current_user_agent}")
        try:
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-infobars',
                    '--window-size=1920,1080',
                    '--enable-features=ClipboardAPI',
                    '--enable-blink-features=ClipboardAPI',
                ]
            )
            print("[setup] browser launched")
        except Exception as e:
            print(f"[setup] browser launch failed: {e}")
            raise

        viewport_width = random.randint(1280, 1920)
        viewport_height = random.randint(800, 1080)

        self.context = await self.browser.new_context(
            viewport={'width': viewport_width, 'height': viewport_height},
            user_agent=self.current_user_agent,
            locale='en-US',
            timezone_id='America/New_York',
            java_script_enabled=True,
            has_touch=False,
            is_mobile=False,
            permissions=["clipboard-read", "clipboard-write"],
        )
        self.page = await self.context.new_page()

        # Quick debug screenshot to confirm visible page (if possible)
        try:
            await self.page.goto('about:blank')
            await self.page.wait_for_timeout(200)
            debug_path = self.output_dir / 'debug_browser_screenshot.png'
            await self.page.screenshot(path=str(debug_path))
            print(f"[setup] saved debug screenshot to {debug_path}")
        except Exception as e:
            print(f"[setup] failed to take debug screenshot: {e}")
        # Mask webdriver property to avoid detection
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = {runtime: {}};
        """)

        # Handle cookie consent popups
        self.page.on('dialog', lambda dialog: dialog.accept())
        
    async def cleanup(self):
        """Close browser and cleanup (safe - swallow errors during shutdown)."""
        try:
            if self.browser:
                await self.browser.close()
        except Exception as e:
            print(f"[cleanup] Browser close failed: {e}")
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            print(f"[cleanup] Playwright stop failed: {e}")

    def _get_random_delay(self) -> float:
        """Get randomized delay with jitter and backoff for failures."""
        # Base delay: 2-5 seconds with random jitter
        delay = self.base_delay + random.uniform(0, 3)
        # Add small jitter (0-500ms)
        delay += random.uniform(0, 0.5)
        # Increase delay if we've had consecutive failures (backoff)
        if self.consecutive_failures > 0:
            backoff_multiplier = min(self.consecutive_failures, 5)  # Cap at 5x
            delay *= (1 + backoff_multiplier * 0.5)
            print(f"         (backoff: {delay:.1f}s delay due to {self.consecutive_failures} failures)")
        return delay

    async def _human_like_delay(self, min_ms: int = 100, max_ms: int = 500):
        """Small random delay to simulate human reaction time."""
        await self.page.wait_for_timeout(random.randint(min_ms, max_ms))

    async def _human_like_scroll(self):
        """Perform human-like scrolling behavior."""
        # Random scroll down
        scroll_amount = random.randint(100, 400)
        await self.page.evaluate(f'window.scrollBy(0, {scroll_amount})')
        await self._human_like_delay(200, 600)

        # Sometimes scroll back up a bit
        if random.random() < 0.3:
            scroll_back = random.randint(50, 150)
            await self.page.evaluate(f'window.scrollBy(0, -{scroll_back})')
            await self._human_like_delay(100, 300)

    async def _human_like_mouse_move(self):
        """Simulate random mouse movements."""
        try:
            # Get viewport size
            viewport = self.page.viewport_size
            if viewport:
                # Move mouse to random position
                x = random.randint(100, viewport['width'] - 100)
                y = random.randint(100, viewport['height'] - 100)
                await self.page.mouse.move(x, y)
                await self._human_like_delay(50, 200)
        except:
            pass  # Ignore mouse movement errors

    async def handle_cookie_consent(self):
        """Click away cookie consent banners if present."""
        try:
            consent_selectors = [
                'button:has-text("Accept")',
                'button:has-text("Accept All")',
                'button:has-text("I agree")',
                '[class*="cookie"] button',
                '[class*="consent"] button'
            ]
            for selector in consent_selectors:
                try:
                    btn = self.page.locator(selector)
                    if await btn.count() > 0:
                        await btn.first.click()
                        await self.page.wait_for_timeout(500)
                        break
                except:
                    continue
        except:
            pass

    async def handle_overlays(self):
        """Attempt to close or remove common overlays/popups that may block UI elements."""
        try:
            # Try common close buttons first
            close_selectors = [
                'button[aria-label="Close"]',
                'button:has-text("Close")',
                'button:has-text("×")',
                'button[title="Close"]',
                '.tv-dialog__close',
                '.tv-modal__close',
                '.modal-close',
                '.overlay__close',
                '.js-close',
                '.tv-toast__close',
                'button[aria-label*="dismiss"]',
                'button:has-text("Sluiten")',
                'button:has-text("Doorgaan")'
            ]
            for sel in close_selectors:
                try:
                    btns = self.page.locator(sel)
                    count = await btns.count()
                    for i in range(count):
                        b = btns.nth(i)
                        if await b.is_visible():
                            try:
                                await b.click()
                                await self.page.wait_for_timeout(300)
                            except:
                                # As fallback, hide the parent overlay element
                                try:
                                    await self.page.evaluate('(s) => { const el = document.querySelector(s); if(el) { el.style.display="none"; el.style.pointerEvents="none"; } }', sel)
                                except:
                                    pass
                except:
                    continue

            # Also aggressively remove some known overlay containers
            overlay_selectors = ['#overlap-manager-root', '[data-qa-id="overlap-manager-root"]', 'div[id^="overlay"]', 'div[class*="overlay"]', 'div[class*="popup"]', '.tv-modal', '.tv-overlay']
            for osel in overlay_selectors:
                try:
                    await self.page.evaluate('(s) => { document.querySelectorAll(s).forEach(e => { e.style.display = "none"; e.style.visibility = "hidden"; e.style.pointerEvents = "none"; }); }', osel)
                except:
                    continue

            # Small wait for DOM to settle
            await self.page.wait_for_timeout(300)
        except:
            pass

    async def get_scripts_from_listing(self, max_scroll_attempts: int | None = 20, debug_pages: bool = False) -> list[dict]:
        """Get all scripts by scrolling/clicking and following paginated pages.

        If max_scroll_attempts is None, keep trying until the page stabilizes
        (no new scripts found for several iterations).

        debug_pages: when True, print per-page visit info and counts for troubleshooting.
        """
        scripts = {}
        last_count = 0
        no_change_count = 0
        
        # Use a click loop similar to the fixed downloader: try 'Show more' up to a limit, checking visibility
        click_count = 0
        max_clicks = max_scroll_attempts if isinstance(max_scroll_attempts, int) else 30
        while click_count < max_clicks:
            # Get current scripts using a slightly stricter pattern (include slugs)
            current_scripts = await self.page.evaluate(r'''() => {
                const scripts = [];
                const links = document.querySelectorAll('a');
                links.forEach(link => {
                    const href = link.href;
                    // Include /script/ links, exclude comment links
                    if (href &&
                        href.includes('/script/') &&
                        href.match(/\/script\/[A-Za-z0-9]+/) &&
                        !href.endsWith('#chart-view-comment-form')) {

                        // Clean URL: remove query params and hash
                        const cleanUrl = href.split('?')[0].split('#')[0];
                        const title = link.textContent?.trim();

                        if (!scripts.some(s => s.url === cleanUrl)) {
                            scripts.push({
                                url: cleanUrl,
                                title: (title && title.length > 3) ? title.substring(0, 200) : 'Unknown'
                            });
                        }
                    }
                });
                return scripts;
            }''')

            # Add to collection
            prev_count = len(scripts)
            for s in current_scripts:
                if s['url'] not in scripts:
                    scripts[s['url']] = s

            print(f"   Found {len(scripts)} scripts... (clicks {click_count})", end='\r')

            # If no new scripts, attempt to click 'Show more' if visible
            if len(scripts) == prev_count:
                try:
                    show_more = self.page.locator('button:has-text("Show more")')
                    if await show_more.count() > 0 and await show_more.first.is_visible():
                        try:
                            await show_more.first.click()
                            if debug_pages:
                                print(f"   [debug] Clicked 'Show more' (clicks so far: {click_count + 1})")
                        except Exception:
                            # Try cookie consent, overlay removal and force click
                            try:
                                await self.handle_cookie_consent()
                                if debug_pages:
                                    print("   [debug] Tried cookie consent during 'Show more' failure")
                            except:
                                pass
                            try:
                                await self.page.evaluate(r'''() => {
                                    const els = document.querySelectorAll('#overlap-manager-root, [data-qa-id="overlap-manager-root"], div[id^="overlay"], div[class*="overlay"], canvas');
                                    els.forEach(e => e.style.pointerEvents = 'none');
                                }''')
                                if debug_pages:
                                    print("   [debug] Removed overlay pointer-events during 'Show more' failure")
                            except:
                                pass
                            try:
                                await show_more.first.click(force=True)
                                if debug_pages:
                                    print("   [debug] Force-clicked 'Show more'")
                            except Exception:
                                # give up on this button
                                if debug_pages:
                                    print("   [debug] Failed to click 'Show more' (giving up)")
                                break

                        await self.page.wait_for_timeout(1800)
                        click_count += 1
                        continue
                    else:
                        break
                except Exception:
                    break
            else:
                # Reset click counter when new scripts are found
                click_count = 0

            await self.page.wait_for_timeout(600)

        print()  # New line after progress

        # If the listing uses numbered pagination or the above failed to gather enough, gather page links and visit them
        try:
            page_links = await self.page.evaluate(r'''() => {
                const pages = new Set();
                const anchors = Array.from(document.querySelectorAll('a'));
                anchors.forEach(a => {
                    try {
                        const href = (a.href || '').split('#')[0];
                        if (!href) return;
                        if (href.match(/\?page=\d+/) || href.match(/\/page-\d+/) || (a.rel && a.rel.toLowerCase() === 'next')) {
                            pages.add(href);
                        }
                    } catch(e) {}
                });
                // Also include <link rel="next"> if present
                try {
                    const l = document.querySelector('link[rel="next"]');
                    if (l && l.href) pages.add(l.href.split('#')[0]);
                } catch(e) {}
                return Array.from(pages);
            }''')

            # Visit each pagination link and collect scripts (limit to reasonable amount)
            if page_links:
                page_links = sorted(set(page_links))[:40]
                for idx, purl in enumerate(page_links, 1):
                    try:
                        if debug_pages:
                            print(f"   [debug] Visiting numbered page {idx}/{len(page_links)}: {purl}")
                        else:
                            print(f"   Visiting page {idx}/{len(page_links)}: {purl}")
                        await self.page.goto(purl, wait_until='networkidle', timeout=30000)
                        await self.page.wait_for_timeout(1200)
                        page_scripts = await self.page.evaluate(r'''() => {
                            const scripts = [];
                            const links = document.querySelectorAll('a');
                            links.forEach(link => {
                                const href = link.href;
                                // Include /script/ links, exclude comment links and duplicates
                                if (href && href.includes('/script/') && href.match(/\/script\/[A-Za-z0-9]+/) && !href.endsWith('#chart-view-comment-form')) {
                                    const cleanUrl = href.split('?')[0].split('#')[0];
                                    const title = link.textContent?.trim();
                                    if (!scripts.some(s => s.url === cleanUrl)) {
                                        scripts.push({url: cleanUrl, title: (title && title.length > 3) ? title.substring(0,200) : 'Unknown'});
                                    }
                                }
                            });
                            return scripts;
                        }''')
                        found_total = len(page_scripts)
                        new_found = 0
                        new_urls = []
                        for s in page_scripts:
                            if s['url'] not in scripts:
                                scripts[s['url']] = s
                                new_found += 1
                                new_urls.append(s['url'])
                        if debug_pages:
                            print(f"   [debug] Numbered page {idx} found {found_total} scripts, new {new_found}")
                            if new_found > 0:
                                print(f"   [debug] New URLs (sample): {', '.join(new_urls[:8])}")
                    except:
                        continue

            # Programmatic page visits up to max_scroll_attempts (fallback / explicit)
            try:
                if isinstance(max_scroll_attempts, int) and max_scroll_attempts > 1:
                    parsed = urlparse(self.page.url)
                    # Remove any '/page-N' segment from path before generating ?page= urls
                    import re as _re
                    clean_path = _re.sub(r'/page-\d+', '', parsed.path)
                    base = parsed.scheme + '://' + parsed.netloc + clean_path
                    existing_q = parsed.query
                    no_new_pages = 0
                    for p in range(2, max_scroll_attempts + 1):
                        # Build URL: preserve existing query params but replace/add page
                        if existing_q:
                            # Remove existing page= param if present
                            q = '&'.join([kv for kv in existing_q.split('&') if not kv.startswith('page=')])
                            q = (q + '&') if q else ''
                            page_url = base + '?' + q + f'page={p}'
                        else:
                            page_url = base + f'?page={p}'

                        if debug_pages:
                            print(f"   [debug] Visiting generated page {p}: {page_url}")
                        else:
                            print(f"   Visiting generated page {p}: {page_url}")
                        await self.page.goto(page_url, wait_until='networkidle', timeout=30000)
                        await self.page.wait_for_timeout(1200)
                        page_scripts = await self.page.evaluate(r'''() => {
                            const scripts = [];
                            const links = document.querySelectorAll('a');
                            links.forEach(link => {
                                const href = link.href;
                                if (href && href.includes('/script/') && href.match(/\/script\/[A-Za-z0-9]+/) && !href.endsWith('#chart-view-comment-form')) {
                                    const cleanUrl = href.split('?')[0].split('#')[0];
                                    const title = link.textContent?.trim();
                                    if (!scripts.some(s => s.url === cleanUrl)) {
                                        scripts.push({url: cleanUrl, title: (title && title.length > 3) ? title.substring(0,200) : 'Unknown'});
                                    }
                                }
                            });
                            return scripts;
                        }''')
                        found_total = len(page_scripts)
                        new_found = 0
                        for s in page_scripts:
                            if s['url'] not in scripts:
                                scripts[s['url']] = s
                                new_found += 1
                        if debug_pages:
                            print(f"   [debug] Generated page {p} found {found_total} scripts, new {new_found}")
                        if new_found == 0:
                            no_new_pages += 1
                            if no_new_pages >= 3:
                                if debug_pages:
                                    print(f"   [debug] {no_new_pages} consecutive generated pages had no new scripts, stopping generated page visits")
                                break
            except Exception:
                pass
        except:
            pass

        return list(scripts.values())
        


    async def extract_pine_source(self, script_url: str) -> dict:
        """
        Extract Pine Script source code using multiple strategies.
        Returns dict with: source_code, title, version, is_strategy, error
        """
        result = {
            'url': script_url,
            'script_id': extract_script_id(script_url),
            'title': '',
            'source_code': '',
            'version': '',
            'is_strategy': False,
            'is_protected': False,
            'author': '',
            'published_date': '',
            'description': '',
            'tags': [],
            'boosts': 0,
            'error': None
        }
        
        try:
            response = await self.page.goto(script_url, wait_until='domcontentloaded', timeout=30000)
            if not response or response.status >= 400:
                result['error'] = f"HTTP {response.status if response else 'No response'}"
                return result

            # Human-like behavior: wait, scroll, move mouse
            await self.page.wait_for_timeout(random.randint(1500, 2500))
            await self.handle_cookie_consent()
            await self._human_like_mouse_move()
            await self._human_like_scroll()
            
            # Extract metadata
            result['title'] = await self.page.evaluate(r'''() => {
                const h1 = document.querySelector('h1');
                return h1 ? h1.textContent.trim() : '';
            }''')
            
            result['author'] = await self.page.evaluate(r'''() => {
                const authorLink = document.querySelector('a[href^="/u/"]');
                return authorLink ? authorLink.textContent.trim().replace('by ', '') : '';
            }''')

            # Extract extended metadata (published date, description, tags, stats)
            extended_meta = await self.page.evaluate(r'''() => {
                const meta = {
                    published_date: '',
                    description: '',
                    tags: [],
                    boosts: 0
                };

                // Published date from time element
                const timeEl = document.querySelector('time');
                if (timeEl) {
                    meta.published_date = timeEl.getAttribute('datetime') || timeEl.textContent.trim();
                }

                // Description from page content (full text), fallback to meta tag
                const descDiv = document.querySelector('div[class*="description"]');
                if (descDiv) {
                    meta.description = descDiv.innerText.trim();
                } else {
                    const metaDesc = document.querySelector('meta[name="description"]');
                    if (metaDesc) {
                        meta.description = metaDesc.getAttribute('content') || '';
                    }
                }

                // Tags from section with tags class
                const tagSection = document.querySelector('section[class*="tags"]');
                if (tagSection) {
                    const tagLinks = tagSection.querySelectorAll('a[href*="/scripts/"]');
                    tagLinks.forEach(a => {
                        const tagName = a.textContent.trim();
                        if (tagName && !meta.tags.includes(tagName)) {
                            meta.tags.push(tagName);
                        }
                    });
                }

                // Boosts from aria-label (e.g., "836 boosts")
                const boostSpan = document.querySelector('span[aria-label*="boosts"]');
                if (boostSpan) {
                    const label = boostSpan.getAttribute('aria-label') || '';
                    const match = label.match(/(\\d+)/);
                    if (match) meta.boosts = parseInt(match[1], 10);
                }

                return meta;
            }''')

            # Merge extended metadata
            result['published_date'] = extended_meta.get('published_date', '')
            result['description'] = extended_meta.get('description', '')
            result['tags'] = extended_meta.get('tags', [])
            result['boosts'] = extended_meta.get('boosts', 0)

            # Check if open-source (FIXED: look for explicit open-source indicator, not lock icons)
            script_type = await self.page.evaluate(r'''() => {
                const pageText = document.body.innerText;
                const pageUpper = pageText.toUpperCase();
                
                // Check for explicit OPEN-SOURCE indicator
                const isOpenSource = pageUpper.includes('OPEN-SOURCE SCRIPT') || 
                                    pageUpper.includes('OPEN-SOURCE') ||
                                    pageText.includes('Open-source script');
                
                // Check for invite-only or protected (these override open-source)
                const isInviteOnly = pageText.toLowerCase().includes('invite-only');
                const isProtected = pageText.toLowerCase().includes('protected script');
                
                return {
                    isOpenSource: isOpenSource && !isInviteOnly && !isProtected,
                    isInviteOnly,
                    isProtected
                };
            }''')
            
            if not script_type['isOpenSource']:
                result['is_protected'] = True
                if script_type['isInviteOnly']:
                    result['error'] = 'invite-only'
                elif script_type['isProtected']:
                    result['error'] = 'protected'
                else:
                    result['error'] = 'not open-source'
                return result
            
            # Only use clipboard/copy-button extraction. No fallback.
            try:
                # Try to click the Source code tab first to reveal code & copy icon
                tab_selectors = ['[role="tab"]:has-text("Source code")','button:has-text("Source code")','div:has-text("Source code"):not(:has(*))','button:has-text("Source")']
                for s in tab_selectors:
                    try:
                        t = self.page.locator(s)
                        if await t.count() > 0 and await t.first.is_visible():
                            try:
                                # Ensure overlays are cleared and the tab is scrolled into view
                                await self.handle_overlays()
                                await t.first.evaluate('el => el.scrollIntoView({block: "center"})')
                                await t.first.click()
                                await self.page.wait_for_timeout(600)
                                if getattr(self, 'debug_pages', False):
                                    print(f"   [debug] Clicked Source code tab using selector: {s}")
                                break
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                pass


            # Probeer tot 3 keer clipboard/copy-knop extractie
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                # Ensure overlays removed before each attempt
                try:
                    await self.handle_overlays()
                except Exception:
                    pass

                source_code = await self._try_copy_button_extraction()
                if source_code:
                    # Mark that this source came directly from the copy-to-clipboard flow and
                    # keep the raw captured value so we can save it byte-for-byte later.
                    result['source_origin'] = 'clipboard'
                    result['source_raw'] = source_code
                    break
                if getattr(self, 'debug_pages', False):
                    print(f"   [debug] Clipboard extractie poging {attempt} mislukt voor {script_url}")
                # Recovery steps
                try:
                    if attempt == 2:
                        if getattr(self, 'debug_pages', False):
                            print("   [debug] Removing overlays and retrying Source tab (recovery)")
                        await self.handle_overlays()
                        await self.page.wait_for_timeout(800)
                        # try to click source tab again safely
                        try:
                            tab_selectors = ['[role="tab"]:has-text("Source code")','button:has-text("Source code")','div:has-text("Source code"):not(:has(*))','button:has-text("Source")']
                            for s in tab_selectors:
                                try:
                                    t = self.page.locator(s)
                                    if await t.count() > 0 and await t.first.is_visible():
                                        try:
                                            await t.first.evaluate('el => el.scrollIntoView({block: "center"})')
                                            await t.first.click()
                                            await self.page.wait_for_timeout(600)
                                            if getattr(self, 'debug_pages', False):
                                                print(f"   [debug] Clicked Source code tab using selector: {s} (recovery)")
                                            break
                                        except Exception:
                                            continue
                                except Exception:
                                    continue
                        except Exception:
                            pass
                    elif attempt == 3:
                        if getattr(self, 'debug_pages', False):
                            print("   [debug] Restarting browser context as recovery...")
                        try:
                            await self.cleanup()
                        except Exception:
                            pass
                        await self.setup()
                        # Re-navigate to the script page and re-open source tab after restart
                        try:
                            await self.page.goto(script_url, wait_until='networkidle', timeout=45000)
                            await self.page.wait_for_timeout(1200)
                            await self.handle_overlays()
                            tab_selectors = ['[role="tab"]:has-text("Source code")','button:has-text("Source code")','div:has-text("Source code"):not(:has(*))','button:has-text("Source")']
                            for s in tab_selectors:
                                try:
                                    t = self.page.locator(s)
                                    if await t.count() > 0 and await t.first.is_visible():
                                        try:
                                            await t.first.evaluate('el => el.scrollIntoView({block: "center"})')
                                            await t.first.click()
                                            await self.page.wait_for_timeout(600)
                                            if getattr(self, 'debug_pages', False):
                                                print(f"   [debug] Clicked Source code tab using selector: {s} (post-restart)")
                                            break
                                        except Exception:
                                            continue
                                except Exception:
                                    continue
                        except Exception:
                            pass
                except Exception:
                    pass
                await self.page.wait_for_timeout(1200)
            if not source_code:
                result['error'] = 'clipboard_extraction_failed'
                return result

            # Normalize encoding/whitespace before further processing
            try:
                source_code = self._normalize_source(source_code)
            except Exception:
                pass
            result['source_code'] = source_code.strip()
            # Detect version and type from normalized source
            version_match = re.search(r'//@version=(\d+)', result['source_code'])


            return result
            
        except PlaywrightTimeoutError:
            result['error'] = 'Timeout'
            return result
        except Exception as e:
            result['error'] = str(e)[:100]
            return result

    async def _try_source_tab_extraction(self) -> str:
        """Try clicking Source Code tab and extracting."""
        try:
            # Human-like behavior before clicking
            await self._human_like_mouse_move()
            await self._human_like_delay(200, 500)

            # Find and click Source Code tab (extra selectors)
            tab_selectors = [
                '[role="tab"]:has-text("Source code")',
                'button:has-text("Source code")',
                'div:has-text("Source code"):not(:has(*))',
                'button:has-text("Source")',
                'a:has-text("Source")',
                'button:has-text("Show source")',
            ]

            for selector in tab_selectors:
                try:
                    tab = self.page.locator(selector)
                    if await tab.count() > 0:
                        # Move mouse near the tab before clicking
                        await self._human_like_delay(100, 300)
                        await tab.first.click()
                        await self.page.wait_for_timeout(random.randint(1500, 3000))
                        break
                except:
                    continue
            
            # Extract code - FIXED: Look for container with many child divs (line-by-line code)
            code = await self.page.evaluate(r'''() => {
                // Find all divs and look for containers with many child divs
                const allDivs = document.querySelectorAll('div');
                
                for (const container of allDivs) {
                    const children = Array.from(container.children);
                    
                    // If this div has many child divs (or smaller code blocks), it might be the code container
                    if (children.length >= 12) {
                        const texts = children.map(c => c.textContent?.trim() || '');
                        const joined = texts.join('\n');
                        // Accept library declarations and other Pine identifiers
                        if ((joined.includes('//@version') || joined.includes('indicator(') || joined.includes('strategy(') || joined.includes('library(') || joined.includes('plot(') || joined.toLowerCase().includes('library ')) && joined.length > 100) {
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

                // NEW FALLBACK: Find the visible "Pine Script" section header and grab adjacent code container
                try {
                    const headers = Array.from(document.querySelectorAll('*')).filter(el => {
                        const t = (el.textContent || '').trim();
                        return t && (t.toLowerCase().includes('pine script') || t.toLowerCase().includes('pine script®'));
                    });
                    for (const h of headers) {
                        // look for code-like sibling or descendant
                        let candidate = null;
                        // check next siblings
                        let sib = h.nextElementSibling;
                        while (sib) {
                            const txt = (sib.textContent || '').trim();
                            if (txt.length > 100 && (txt.includes('//@version') || txt.includes('library(') || txt.includes('indicator('))) {
                                candidate = txt; break;
                            }
                            sib = sib.nextElementSibling;
                        }
                        if (candidate) return candidate;
                        // else check descendants of parent
                        const parent = h.parentElement;
                        if (parent) {
                            const bigText = parent.innerText || '';
                            if (bigText.includes('//@version') || bigText.includes('library(')) {
                                return bigText;
                            }
                        }
                    }
                } catch(e) {}

                return '';
            }''')
            
            return code
        except:
            return ''

    async def _try_direct_extraction(self) -> str:
        """Try extracting code directly from page elements."""
        try:
            return await self.page.evaluate(r'''() => {
                // Method 1: Look for containers with many child divs (line-by-line code)
                const allDivs = document.querySelectorAll('div');
                
                for (const container of allDivs) {
                    const children = Array.from(container.children);
                    
                    if (children.length >= 8) {
                        const texts = children.map(c => c.textContent?.trim() || '');
                        const joined = texts.join('\n');
                        if ((joined.includes('//@version') || joined.includes('indicator(') || joined.includes('strategy(') || joined.includes('library(') || joined.includes('plot(')) && joined.length > 80) {
                            const codeLines = texts.filter(t => t && !/^\\d+$/.test(t));
                            return codeLines.join('\\n');
                        }
                    }
                }
                
                // Method 2: Look for any pre/code element with Pine Script content
                const codeElements = document.querySelectorAll('pre, code, [class*="source"]');

                for (const elem of codeElements) {
                    const text = elem.textContent || '';
                    if (text.length > 100 && 
                        (text.includes('//@version') || 
                         text.includes('indicator(') || 
                         text.includes('strategy(') ||
                         text.includes('plot('))) {
                        return text;
                    }
                }

                // Method 3: Look for a heading that says 'Pine Script' and take the next block(s)
                const headings = document.querySelectorAll('h1,h2,h3,h4,div');
                for (const h of headings) {
                    try {
                        const txt = (h.textContent || '').trim().toLowerCase();
                        if (txt.includes('pine script')) {
                            let node = h.nextElementSibling;
                            while (node) {
                                const t = node.textContent || '';
                                if (t.length > 100 && (t.includes('//@version') || t.includes('indicator(') || t.includes('strategy(') || t.includes('plot('))) {
                                    return t;
                                }
                                node = node.nextElementSibling;
                            }
                        }
                    } catch(e) {}
                }

                return '';
            }''')
        except:
            return ''

    async def _try_embedded_extraction(self) -> str:
        """Try extracting code from embedded page data."""
        try:
            return await self.page.evaluate(r'''() => {
                // Check for script data in page scripts
                const scripts = document.querySelectorAll('script');
                for (const script of scripts) {
                    const content = script.textContent || '';
                    // Look for Pine Script patterns in JSON data (double- or single-quoted)
                    let match = content.match(/"source"\s*:\s*"((?:\\\\.|[^"\\\\])*)"/s);
                    if (!match) match = content.match(/'source'\s*:\s*'((?:\\\\.|[^'\\\\])*)'/s);
                    if (match) {
                        let decoded = match[1]
                            .replace(/\\\\n/g, '\\n')
                            .replace(/\\\\t/g, '\\t')
                            .replace(/\\\\\"/g, '"')
                            .replace(/\\\\'/g, "'");
                        if (decoded.includes('//@version') || decoded.includes('indicator(') || decoded.includes('library(') || decoded.includes('plot(')) {
                            return decoded;
                        }
                    }

                    // Sometimes the source is in a different key like 'body' or 'script'
                    match = content.match(/"body"\s*:\s*"((?:\\\\.|[^"\\\\])*)"/s);
                    if (match) {
                        let decoded = match[1].replace(/\\\\n/g, '\\n');
                        if (decoded.includes('//@version') || decoded.includes('indicator(') || decoded.includes('library(')) {
                            return decoded;
                        }
                    }
                }
                return '';
            }''')
        except:
            return ''

    async def _try_copy_button_extraction(self) -> str:
        """Try extracting source code by searching for copy buttons and clicking them using Playwright locators."""
        btn_selectors = [
            'button[aria-label*="copy"]',
            'button[title*="Copy"]',
            'button[aria-label*="Copy to clipboard"]',
            'button:has-text("Copy")',
            'button:has-text("Copy to clipboard")',
            '.copy-to-clipboard',
            '[data-qa-id*="copy"]',
            '[class*="copy"]',
            '.tv-copy'
        ]

        # 1) Check common data attributes that may hold the source directly
        try:
            attrs = ['data-clipboard-text', 'data-clipboard', 'data-copy', 'data-clipboard-text-original', 'data-clipboard-text-original-value']
            for a in attrs:
                try:
                    v = await self.page.evaluate('(a) => { const el = document.querySelector("["+a+"]"); return el ? el.getAttribute(a) : ""; }', a)
                    if v and ("//@version" in v or "indicator(" in v or "library(" in v or "plot(" in v):
                        return v
                except Exception:
                    continue
        except Exception:
            pass

        # 2) Iterate visible copy buttons (bottom-up), click and try to read clipboard
        try:
            for sel in btn_selectors:
                try:
                    loc = self.page.locator(sel)
                    count = await loc.count()
                    if count == 0:
                        continue
                    for idx in range(count - 1, -1, -1):
                        btn = loc.nth(idx)
                        try:
                            if not await btn.is_visible():
                                continue
                            # remove overlays that might block interaction
                            try:
                                await self.handle_overlays()
                            except Exception:
                                pass

                            # scroll into view and click
                            try:
                                await btn.evaluate('el => el.scrollIntoView({block: "center"})')
                            except Exception:
                                pass
                            try:
                                await btn.click()
                            except Exception:
                                try:
                                    await btn.click(force=True)
                                except Exception:
                                    continue

                            # small wait then attempt to read any in-page captured copy data first (more reliable than OS clipboard in some environments)
                            await self.page.wait_for_timeout(500)
                            try:
                                tmp = await self.page.evaluate('''() => {
                                    if (window.__copied__ && typeof window.__copied__ === 'string') return window.__copied__;
                                    if (window.__copied_source__ && typeof window.__copied_source__ === 'string') return window.__copied_source__;
                                    const ta = document.querySelector('textarea'); if (ta && ta.value) return ta.value;
                                    const inp = document.querySelector('input[type="text"]'); if (inp && inp.value) return inp.value;
                                    const sel = (window.getSelection && window.getSelection().toString()) || '';
                                    return sel || '';
                                }''')
                                if getattr(self, 'debug_pages', False):
                                    short = (tmp[:200] + '...') if tmp and len(tmp) > 200 else (tmp or '')
                                    print(f"   [debug] tmp-capture snippet: {short!r} (len={len(tmp) if tmp else 0})")
                                if tmp and ("//@version" in tmp or "indicator(" in tmp or "library(" in tmp or "plot(" in tmp):
                                    return tmp
                            except Exception:
                                pass

                            # fallback: try reading navigator.clipboard (OS clipboard)
                            try:
                                cb = await self.page.evaluate('navigator.clipboard && navigator.clipboard.readText ? navigator.clipboard.readText() : ""')
                                if getattr(self, 'debug_pages', False):
                                    short = (cb[:200] + '...') if cb and len(cb) > 200 else (cb or '')
                                    print(f"   [debug] navigator.clipboard.readText snippet: {short!r} (len={len(cb) if cb else 0})")
                                if cb and ("//@version" in cb or "indicator(" in cb or "library(" in cb or "plot(" in cb):
                                    return cb
                            except Exception:
                                pass

                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            pass

        return ''

    async def dump_copy_diagnostics(self, url: str):
        """Visit a single script URL and print diagnostics for copy-button capture attempts."""
        await self.setup()
        try:
            # Inject copy-capture helpers *before* any page scripts run
            await self.page.add_init_script(r'''() => {
                window.__cv = window.__cv || { captures: [], mutations: [], logs: [] };
                document.addEventListener('copy', function(e){
                    try { const t = (e.clipboardData && e.clipboardData.getData('text/plain')) || document.getSelection().toString(); if (t) window.__cv.captures.push(t); window.__cv.logs.push({type:'copy-event', text:t, time:Date.now()}); } catch(e){}
                }, true);
                function patchAllCopyFuncs(obj) {
                    for (const k of Object.getOwnPropertyNames(obj)) {
                        if (typeof obj[k] === 'function' && k.toLowerCase().includes('copy')) {
                            const orig = obj[k];
                            obj[k] = function(...args){ try{ window.__cv.logs.push({type:'func', name:k, args, time:Date.now()}); }catch(e){}; let res = orig.apply(this, args); try{ if (typeof res === 'string' && res.includes('//@version')) window.__cv.captures.push(res); }catch(e){}; return res; };
                        }
                    }
                }
                try{ patchAllCopyFuncs(window); }catch(e){}
                try{ patchAllCopyFuncs(document); }catch(e){}
                try {
                    const origWrite = navigator.clipboard && navigator.clipboard.writeText;
                    if (origWrite) {
                        navigator.clipboard.writeText = async function(t){ try{ window.__cv.captures.push(t || ''); window.__cv.logs.push({type:'clipboard.writeText', text:t, time:Date.now()}); }catch(e){}; return origWrite.call(this, t); };
                    } else {
                        navigator.clipboard = { writeText: async function(t){ try{ window.__cv.captures.push(t || ''); window.__cv.logs.push({type:'clipboard.writeText', text:t, time:Date.now()}); }catch(e){}; } };
                    }
                } catch(e){}
                try {
                    const origExec = Document.prototype.execCommand;
                    Document.prototype.execCommand = function(cmd){ if (cmd === 'copy') { try{ window.__cv.captures.push(document.getSelection().toString()); window.__cv.logs.push({type:'execCommand', selection:document.getSelection().toString(), time:Date.now()}); }catch(e){} } return origExec.apply(this, arguments); };
                } catch(e){}
                try {
                    const mo = new MutationObserver((muts) => { for (const m of muts) { for (const n of Array.from(m.addedNodes || [])) { try { const t = (n && n.textContent) ? String(n.textContent) : ''; if (t && (t.includes('//@version') || t.includes('indicator(') || t.includes('strategy(') || t.includes('library(') || t.includes('plot('))) { window.__cv.mutations.push(t); window.__cv.logs.push({type:'mutation', text:t, time:Date.now()}); } } catch(e){} } } }); mo.observe(document, { childList: true, subtree: true }); window.__cv._mo = true;
                } catch(e){}
                const origAddEventListener = EventTarget.prototype.addEventListener;
                EventTarget.prototype.addEventListener = function(type, ...rest){ if (type && (type.toLowerCase().includes('copy') || type.toLowerCase().includes('clipboard'))) { try{ window.__cv.logs.push({type:'addEventListener', event:type, target:this && this.tagName, time:Date.now()}); }catch(e){} } return origAddEventListener.call(this, type, ...rest); };
            }''')
            print('   [debug] Injected copy-capture init script')
            print(f"Diagnostics: visiting {url}")
            await self.page.goto(url, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_timeout(800)

            # try to open source tab so copy-button inside source becomes visible
            try:
                tab_selectors = ['[role="tab"]:has-text("Source code")','button:has-text("Source code")','div:has-text("Source code"):not(:has(*))','button:has-text("Source")']
                for s in tab_selectors:
                    try:
                        t = self.page.locator(s)
                        if await t.count() > 0 and await t.first.is_visible():
                            try:
                                await t.first.click()
                                await self.page.wait_for_timeout(800)
                                print('   [debug] Clicked Source code tab for diagnostics')
                                break
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                pass

            data = await self.page.evaluate(r'''async () => {
                function looksLikePine(t){ return t && (t.includes('//@version') || t.includes('indicator(') || t.includes('strategy(') || t.includes('library(') || t.includes('plot(')); }
                const attrs = ['data-clipboard-text','data-clipboard','data-copy','data-clipboard-text-original','data-clipboard-text-original-value'];
                const btnSelectors = ['button[aria-label*="copy"]', 'button[title*="Copy"]','button[aria-label*="Copy to clipboard"]','.copy-to-clipboard','[data-qa-id*="copy"]','[class*="copy"]','.tv-copy'];
                const found = {attrs: [], buttons: []};
                for (const a of attrs){ const el=document.querySelector('['+a+']'); if(el) found.attrs.push({attr: a, sample:(el.getAttribute(a)||'').slice(0,200) }); }
                for (const sel of btnSelectors){ const nodes=Array.from(document.querySelectorAll(sel)); nodes.forEach((b,i)=>{ const dialog=b.closest('[role="dialog"]')||b.closest('div')||document.body; const code=dialog.querySelector('pre, code, textarea, [class*="code"], [class*="source"]');
                            let struct = [];
                            try { let candidate = dialog.querySelector('div'); let container = candidate || dialog; try { let p=container; while(p && p.parentElement && container.children.length < 10){ p = p.parentElement; container = p; } } catch(e){}
                                struct = Array.from(container.children).slice(0,10).map(c => ({tag: c.tagName, text: (c.textContent||'').trim().slice(0,200)})); } catch(e){}
                            found.buttons.push({selector: sel, idx:i, text: (b.innerText||'').slice(0,120), nearby: (code? (code.value||code.textContent||'').slice(0,200):''), structureSample: struct}); }); }
                async function tryClick(b){ window.__copied__=''; const handler=(e)=>{ try{ window.__copied__=(e.clipboardData&&e.clipboardData.getData('text/plain'))||'';}catch{} }; document.addEventListener('copy', handler, {once:true}); try{ b.click(); }catch{}; const start=Date.now(); while((Date.now()-start)<2000){ await new Promise(r=>setTimeout(r,150)); if(window.__copied__) break; } try{ document.removeEventListener('copy', handler); }catch{}; let cb=window.__copied__||''; try{ if(!cb && navigator.clipboard && navigator.clipboard.readText) cb=await navigator.clipboard.readText(); }catch{}; return cb.slice(0,400); }
                const caps=[]; const btns=Array.from(document.querySelectorAll(btnSelectors.join(',')));
                for (const b of btns){ caps.push(await tryClick(b)); }
                return {found: found, captures: caps};
            }''')

            # print results
            for a in data.get('found', {}).get('attrs', []):
                print(f"[ATTR] {a['attr']} sample: {a['sample']}")
            for b in data.get('found', {}).get('buttons', []):
                print(f"[BUTTON] {b['selector']} idx={b['idx']} text={b['text']!r} nearby_sample={b.get('nearby','')!r}")
                struct = b.get('structureSample', [])
                if struct:
                    print('  [STRUCTURE SAMPLE]')
                    for child in struct[:8]:
                        print(f"    - {child.get('tag')} : {child.get('text')!r}")
            caps = data.get('captures', [])
            for i, c in enumerate(caps):
                print(f"[CAPTURE {i}] {c!r}")

            try:
                cv = await self.page.evaluate('(function(){ try { return window.__cv || {}; } catch(e) { return {}; } })()')
                if not isinstance(cv, dict):
                    cv = dict(cv or {})
                injected_caps = cv.get('captures', [])
                injected_mut = cv.get('mutations', [])
                print(f"[INJECTED CAPTURES] {injected_caps[:3]!r}")
                print(f"[INJECTED MUTATIONS] {injected_mut[:3]!r}")
            except Exception as e:
                print('   [debug] failed to read window.__cv', e)
        finally:
            await self.cleanup()
        return

    def load_progress(self, category: str) -> set:
        """Load previous progress. Returns set of completed URLs and script IDs."""
        progress_path = self.output_dir / sanitize_filename(category) / '.progress.json'
        urls_and_ids = set()
        if progress_path.exists():
            try:
                with open(progress_path) as f:
                    data = json.load(f)
                    for r in data.get('results', []):
                        if r.get('url'):
                            urls_and_ids.add(r['url'])
                        sid = r.get('script_id')
                        if sid:
                            urls_and_ids.add(sid)
                            try:
                                prefix = sid.split('-')[0]
                                urls_and_ids.add(prefix)
                            except:
                                pass
            except Exception:
                pass
        return urls_and_ids

    def save_progress(self, category: str):
        """Save progress to JSON for resuming."""
        progress_path = self.output_dir / sanitize_filename(category) / '.progress.json'
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        with open(progress_path, 'w') as f:
            json.dump({
                'stats': self.stats,
                'results': self.results,
                'timestamp': datetime.now().isoformat()
            }, f, indent=2)

    def _scan_existing_scripts(self) -> set:
        """Scan output dir for existing .pine files and extract their URLs or script IDs."""
        found = set()
        try:
            for p in self.output_dir.rglob('*.pine'):
                if any(part.startswith('@') or part in self.ignore_dir_prefixes for part in p.parts):
                    continue
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        for _ in range(40):
                            line = f.readline()
                            if not line:
                                break
                            m = re.match(r'\s*//\s*URL:\s*(\S+)', line)
                            if m:
                                found.add(m.group(1).strip())
                                break
                            m2 = re.match(r'\s*//\s*Script ID:\s*(\S+)', line)
                            if m2:
                                sid = m2.group(1).strip()
                                found.add(sid)
                                try:
                                    found.add(sid.split('-')[0])
                                except:
                                    pass
                                break
                except Exception:
                    continue
        except Exception:
            pass
        return found

    def save_script(self, result: dict, category: str) -> Path:
        """Save Pine Script to file with metadata."""
        category_dir = self.output_dir / sanitize_filename(category)
        category_dir.mkdir(parents=True, exist_ok=True)
        
        # Create filename
        safe_title = sanitize_filename(result.get('title') or 'unknown')
        filename = f"{result.get('script_id')}_{safe_title}.pine"
        filepath = category_dir / filename
        
        # Format tags for header
        tags_str = ', '.join(result.get('tags', [])) if result.get('tags') else ''

        # Build header
        header = [
            f"// Title: {result.get('title')}",
            f"// Script ID: {result.get('script_id')}",
            f"// Author: {result.get('author')}",
            f"// URL: {result.get('url')}",
            f"// Published: {result.get('published_date','')}",
            f"// Downloaded: {datetime.now().isoformat()}",
            f"// Pine Version: {result.get('version','')}",
            f"// Type: {'Strategy' if result.get('is_strategy') else 'Indicator'}",
            f"// Boosts: {result.get('boosts',0)}",
            f"// Tags: {tags_str}",
            "//",
            ""
        ]

        # If the script was captured directly from the copy-to-clipboard flow, write the
        # raw captured content verbatim as UTF-8 bytes and do NOT add the generated metadata header
        # (we must avoid automatic newline translation on Windows and keep exact bytes).
        if result.get('source_origin') == 'clipboard' and result.get('source_raw'):
            raw = result.get('source_raw')
            if isinstance(raw, str):
                raw_bytes = raw.encode('utf-8')
            else:
                raw_bytes = str(raw).encode('utf-8')
            # Write exact bytes to disk (binary mode)
            with open(filepath, 'wb') as f:
                f.write(raw_bytes)
            # Also export metadata as a separate JSON sidecar so we do not embed it in the script
            try:
                meta = {
                    'title': result.get('title'),
                    'script_id': result.get('script_id'),
                    'author': result.get('author'),
                    'url': result.get('url'),
                    'downloaded': datetime.now().isoformat(),
                    'tags': result.get('tags', []),
                    'pine_version': result.get('version','')
                }
                meta_path = filepath.with_suffix('.meta.json')
                with open(meta_path, 'w', encoding='utf-8') as mf:
                    json.dump(meta, mf, indent=2)
            except Exception:
                pass
            print(f"Saved raw clipboard script to {filepath} (metadata written to {meta_path})")
            return filepath

        source = result.get('source_code') or ''
        if isinstance(source, str):
            try:
                # Previous code tried to unescape escaped sequences; keep that behavior
                # for non-clipboard sources only.
                if '\\n' in source or '\\t' in source or '\\u' in source:
                    try:
                        source = codecs.decode(source, 'unicode_escape')
                    except Exception:
                        source = source.replace('\\n','\n').replace('\\r','\r').replace('\\t','\t')
                        source = source.replace('\\"','"').replace('\\/','/')
                source = source.strip('\n')
            except Exception:
                pass
        else:
            source = str(source)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(header))
            f.write(source)
            f.write('\n')

        return filepath

    def _export_metadata(self, category: str):
        """Export all metadata to JSON."""
        metadata_path = self.output_dir / sanitize_filename(category) / 'metadata.json'
        export_data = {
            'download_date': datetime.now().isoformat(),
            'category': category,
            'statistics': self.stats,
            'scripts': []
        }
        for r in self.results:
            export_data['scripts'].append({
                'script_id': r.get('script_id'),
                'title': r.get('title'),
                'author': r.get('author'),
                'url': r.get('url'),
                'version': r.get('version'),
                'is_strategy': r.get('is_strategy'),
                'is_protected': r.get('is_protected'),
                'has_source': bool(r.get('source_code')),
                'published_date': r.get('published_date', ''),
                'description': r.get('description', ''),
                'tags': r.get('tags', []),
                'boosts': r.get('boosts', 0),
                'error': r.get('error')
            })
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        print(f"\n📄 Metadata exported: {metadata_path}")

    def _print_summary(self, category: str):
        """Print final summary."""
        print(f"\n{'='*70}")
        print(f"  SUMMARY")
        print(f"{'='*70}")
        print(f"  ✓ Downloaded:          {self.stats['downloaded']}")
        print(f"  ⊘ Protected/Private:   {self.stats['skipped_protected']}")
        print(f"  ⊘ No Source Found:     {self.stats['skipped_no_code']}")
        print(f"  ✗ Failed:              {self.stats['failed']}")
        print(f"  ─────────────────────────────────")
        print(f"  Total Processed:       {len(self.results)}")
        print(f"\n  Output: {self.output_dir / sanitize_filename(category)}")
        print(f"{'='*70}\n")


async def main():
    parser = argparse.ArgumentParser(description='Download Pine Script from TradingView')

    # URL can be provided via CLI or via DOWNLOAD_URL env var
    default_url = os.environ.get('DOWNLOAD_URL')
    parser.add_argument('--url', '-u', default=default_url, help='TradingView scripts URL (or set DOWNLOAD_URL env var)')

    # Default output: prefer env PINE_OUTPUT_DIR, else use /mnt/pinescripts if present, else local folder
    env_output = os.environ.get('PINE_OUTPUT_DIR')
    if env_output:
        default_output = env_output
    elif os.path.exists('/mnt/pinescripts'):
        default_output = '/mnt/pinescripts'
    else:
        default_output = './pinescript_downloads'

    parser.add_argument('--output', '-o', default=default_output, help='Output directory')
    parser.add_argument('--delay', '-d', type=float, default=2.0, help='Delay between requests')
    parser.add_argument('--visible', action='store_true', help='Show browser window')
    parser.add_argument('--no-resume', action='store_true', help='Start fresh (ignore progress)')
    parser.add_argument('--max-pages', '-p', type=int, default=20, help='Maximum pages to scan or visit')
    parser.add_argument('--debug-pages', action='store_true', help='Verbose page visit logging (debug)')
    parser.add_argument('--dump-copy', action='store_true', help='Diagnostic: inspect copy-button(s) and captured clipboard payload on a single script URL')
    parser.add_argument('--status', action='store_true', help='Show status of output directory (progress files, existing .pine files) and exit')

    args = parser.parse_args()

    # Require --url unless --status is used (so --status can run standalone)
    if not args.url and not args.status:
        parser.error('the following arguments are required: --url (unless --status is provided or DOWNLOAD_URL env var is set)')
    
    scraper = EnhancedTVScraper(
        output_dir=args.output,
        headless=not args.visible
    )

    if args.status:
        scraper.print_status()
        return

    if args.dump_copy:
        if not args.url or '/script/' not in args.url:
            parser.error('--dump-copy requires a single script URL (contains "/script/")')
        await scraper.dump_copy_diagnostics(args.url)
        return

    # If a single script URL was provided, run the simple single-script flow instead of download_all
    if args.url and '/script/' in args.url:
        scraper.debug_pages = args.debug_pages
        await scraper.setup()
        try:
            print('Processing single script URL...')
            res = await scraper.extract_pine_source(args.url)
            if res.get('error'):
                print(f"Error: {res.get('error')}")
            elif res.get('source_code'):
                # Use script id as category for single downloads
                category = extract_script_id(args.url) or 'scripts'
                fp = scraper.save_script(res, category)
                # If this was a clipboard capture, verify the written file equals the raw clipboard payload
                if res.get('source_origin') == 'clipboard' and res.get('source_raw'):
                    try:
                        written_bytes = Path(fp).read_bytes()
                        raw_bytes = res.get('source_raw').encode('utf-8')
                        if written_bytes != raw_bytes:
                            print('Warning: written file does not match raw clipboard payload. Overwriting with raw bytes...')
                            Path(fp).write_bytes(raw_bytes)
                        else:
                            print('Verified: saved file matches clipboard content (byte-for-byte)')
                    except Exception as e:
                        print(f'Warning: failed to verify written file: {e}')
                print(f"Saved single script to: {fp}")
            else:
                print('No source code found for single script URL')
        finally:
            await scraper.cleanup()
        return

    # Fallback to batch download (download_all may be implemented in future)
    await scraper.download_all(
        base_url=args.url,
        max_pages=args.max_pages,
        delay=args.delay,
        resume=not args.no_resume,
        debug_pages=args.debug_pages
    )


if __name__ == '__main__':
    asyncio.run(main())

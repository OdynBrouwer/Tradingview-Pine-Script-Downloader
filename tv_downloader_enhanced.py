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
import email.utils
import json
import os
import random
import re
import sys
import codecs
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
# Import TargetClosedError for robust handling of closed contexts/pages
from playwright._impl._errors import TargetClosedError


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
    def __init__(self, output_dir: str | None = None, headless: bool = False, positional_click: bool = False):
        # Positional click mode: when True, try a fixed relative click inside the code container first
        self.positional_click = bool(positional_click)
        # Track clipboard captures seen in this run to detect stale reuse across scripts
        self._seen_clipboard_hashes: dict[str, str] = {}  # sha256 -> script_url (first owner)
        # Fast mode: fewer retries and shorter waits (less reliable but much faster)
        self.fast_mode = False

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
                    '--force-device-scale-factor=1',
                    '--enable-features=ClipboardAPI',
                    '--enable-blink-features=ClipboardAPI',
                ]
            )
            print("[setup] browser launched")
        except Exception as e:
            print(f"[setup] browser launch failed: {e}")
            raise

        # If debug_pages OR positional_click is enabled, inject copy-capture helpers early so we can reliably
        # capture copy events during batch runs (positional mode mimics dump-copy behavior)
        try:
            if getattr(self, 'debug_pages', False) or getattr(self, 'positional_click', False) or getattr(self, 'dump_copy_mode', False):
                await self.page.add_init_script(r'''() => {
                    window.__cv = window.__cv || { captures: [], mutations: [], logs: [] };
                    document.addEventListener('copy', function(e){
                        try { const t = (e.clipboardData && e.clipboardData.getData('text/plain')) || document.getSelection().toString(); if (t) window.__cv.captures.push(t); window.__cv.logs.push({type:'copy-event', text:t, time:Date.now()}); } catch(e){}
                    }, true);
                    try{
                        const origWrite = navigator.clipboard && navigator.clipboard.writeText;
                        if (origWrite) {
                            navigator.clipboard.writeText = async function(t){ try{ window.__cv.captures.push(t || ''); window.__cv.logs.push({type:'clipboard.writeText', text:t, time:Date.now()}); }catch(e){}; return origWrite.call(this, t); };
                    } catch(e){}
                }''')
        except Exception:
            pass

        # Use fixed viewport matching a 16:9 aspect ratio (overridable via env vars)
        # Default changed to 1280×720 (HD) to preserve aspect ratio and speed up rendering.
        # Zet viewport terug naar 1280x720 (standaard)
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent=self.current_user_agent,
            locale='en-US',
            timezone_id='America/New_York',
            java_script_enabled=True,
            has_touch=False,
            is_mobile=False,
            permissions=["clipboard-read", "clipboard-write"],
        )
        self.page = await self.context.new_page()

        # ...debug screenshot code verwijderd...
        # Mask webdriver property to avoid detection
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = {runtime: {}};
        """)

        # Handle cookie consent popups
        self.page.on('dialog', lambda dialog: dialog.accept())
        # Log page lifecycle events for diagnostics (helps debug unexpected closures/crashes)
        try:
            self.page.on('crash', lambda *args: print('[setup] Page crash event detected'))
            self.page.on('close', lambda *args: print('[setup] Page close event detected'))
        except Exception:
            pass
        
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

    def _clean_diagnostic_files(self):
        """Remove diagnostic artifacts from the output directory when running in fast dump-copy mode."""
        try:
            od = Path(self.output_dir)
            if not od.exists():
                return
            # Remove well-known diagnostic files
            for p in od.glob('*_diagnostic.*'):
                try:
                    p.unlink()
                except Exception:
                    pass
            for p in od.glob('*_raw.pine'):
                try:
                    p.unlink()
                except Exception:
                    pass
            for p in ('diagnostic_captures.txt', 'last_result.json'):
                fp = od / p
                try:
                    if fp.exists():
                        fp.unlink()
                except Exception:
                    pass
            # Remove debug_positional directory if present
            dbg = od / 'debug_positional'
            if dbg.exists() and dbg.is_dir():
                try:
                    import shutil
                    shutil.rmtree(dbg, ignore_errors=True)
                except Exception:
                    pass
            print(f"[cleanup] Removed diagnostic artifacts from: {od}")
        except Exception as e:
            print(f"[cleanup] Failed to remove diagnostic files: {e}")

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

            # Also aggressively remove some known overlay containers (do NOT hide the site header globally)
            overlay_selectors = ['#overlap-manager-root', '[data-qa-id="overlap-manager-root"]', 'div[id^="overlay"]', 'div[class*="overlay"]', 'div[class*="popup"]', '.tv-modal', '.tv-overlay', '#credential_picker_container', '.apply-overflow-tooltip']
            for osel in overlay_selectors:
                try:
                    # Only hide elements that do NOT contain the Source tab or a 'Source code' button/text
                    await self.page.evaluate('''(s) => { document.querySelectorAll(s).forEach(e => { try { const hasSource = (function(){ try { const nodes = e.querySelectorAll('*'); for (const n of nodes) { try { const role = n.getAttribute && n.getAttribute('role'); const txt = (n.textContent||'').toLowerCase(); if ((role === 'tab' && txt.includes('source code')) || (n.tagName === 'BUTTON' && txt.includes('source code')) || txt.includes('source code')) return true; } catch(e){} } } catch(e){} return false; })(); if (!hasSource) { e.style.display = 'none'; e.style.visibility = 'hidden'; e.style.pointerEvents = 'none'; } } catch(e){} }); }''', osel)
                except:
                    continue

            # Additionally, try to click any close action on credential picker if present
            try:
                await self.page.evaluate("() => { const c = document.getElementById('credential_picker_container'); if(c){ const btn = c.querySelector('button'); if(btn && btn.click) try{ btn.click(); }catch(e){} } }")
            except:
                pass

            # Specific handling for Google login modal / OAuth iframes (new UI variation)
            try:
                found_google_modal = await self.page.evaluate('''() => {
                    try {
                        // Hide dialogs that contain the Dutch/English Google sign-in copy
                        const keywords = ['inloggen met google', 'gebruik je google', 'use your google'];
                        const nodes = Array.from(document.querySelectorAll('div, dialog, section'));
                        let found = false;
                        for (const n of nodes) {
                            try {
                                const t = (n.textContent || '').toLowerCase();
                                if (keywords.some(k => t.includes(k))) {
                                    n.style.display = 'none'; n.style.visibility = 'hidden'; n.style.pointerEvents = 'none';
                                    found = true;
                                }
                            } catch(e){}
                        }
                        // Also hide iframes that point to Google accounts/sign-in
                        const iframes = Array.from(document.querySelectorAll('iframe'));
                        for (const f of iframes) {
                            try {
                                const src = (f.src || '').toLowerCase();
                                if (src.includes('accounts.google') || src.includes('google.com/accounts') || src.includes('accounts.youtube')) {
                                    f.style.display = 'none'; f.src = 'about:blank'; found = true;
                                }
                            } catch(e){}
                        }
                        return found;
                    } catch(e){ return false; }
                }''')
                if found_google_modal and getattr(self, 'debug_pages', False):
                    print('   [debug] Hid Google login modal or iframe')
            except Exception:
                pass

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
        


    async def extract_exact_publish_date(self):
        """Extract exact publish date using advanced scraping techniques from scrape_pubdates.py."""
        # Try multiple selectors and fallbacks similar to scrape_pubdates.py
        pubtext = await self.page.evaluate("""() => {
            // 0) special handling for <relative-time> which often exposes attributes like event-time / ssr-time
            const relTime = document.querySelector('relative-time');
            if(relTime) {
                const attrs = ['event-time','ssr-time','datetime','title'];
                for(const attr of attrs) {
                    const val = relTime.getAttribute(attr);
                    if(val) return val;
                }
                return relTime.textContent ? relTime.textContent.trim() : '';
            }

            // 1) <time> element
            const timeEl = document.querySelector('time');
            if(timeEl) {
                return timeEl.textContent.trim();
            }

            // 2) explicit 'ago' search: return the matching relative substring (e.g. '6 days ago') when present
            const nodes = Array.from(document.querySelectorAll('div, span, p, li, small, a'));
            for (const n of nodes) {
                const t = (n.textContent||'').trim();
                if (/(\\b|_)ago(\\b|_)/i.test(t)) {
                    const m = t.match(/\\d+\\s+(?:second|minute|hour|day|week|month|year)s?\\s+ago/i);
                    return m ? m[0] : t;
                }
            }

            // 3) header small/date element near title: find any element that looks like a date (month names, 'ago')
            const dateNodes = Array.from(document.querySelectorAll('div, span, p'));
            for (const n of dateNodes) {
                const t = n.textContent || '';
                if(t && /\\b(ago|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\b/i.test(t)) {
                    return t.trim();
                }
            }

            // 4) meta tags
            const meta = document.querySelector('meta[property="article:published_time"]') ||
                        document.querySelector('meta[name="pubdate"]') ||
                        document.querySelector('meta[name="date"]');
            if (meta) {
                return meta.getAttribute('content') || meta.getAttribute('value') || meta.content || '';
            }

            return '';
        }""")

        # Debug output to see what text we extracted
        print(f"[DEBUG] Raw pubtext extracted: '{pubtext}'")

        # Parse the pubtext using similar logic as in scrape_pubdates.py
        if not pubtext:
            print("[DEBUG] No pubtext found, returning None")
            return None

        # Regular expressions from scrape_pubdates.py
        REL_RE = re.compile(r"(?P<num>\d+)\s+(?P<unit>second|minute|hour|day|week|month|year)s?\s+ago", re.I)
        ABS_MONTH_DAY_YEAR = re.compile(r"^(?P<mon>\w{3,9})\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})$")

        s = pubtext.strip()
        # Common relative form like '6 days ago' or '6 days ago' with extra text
        m = REL_RE.search(s)
        now = datetime.now(timezone.utc)
        if m:
            num = int(m.group('num'))
            unit = m.group('unit').lower()
            if unit.startswith('second'):
                dt = now - timedelta(seconds=num)
            elif unit.startswith('minute'):
                dt = now - timedelta(minutes=num)
            elif unit.startswith('hour'):
                dt = now - timedelta(hours=num)
            elif unit.startswith('day'):
                dt = now - timedelta(days=num)
            elif unit.startswith('week'):
                dt = now - timedelta(weeks=num)
            elif unit.startswith('month'):
                # approximate month as 30 days
                dt = now - timedelta(days=30 * num)
            elif unit.startswith('year'):
                dt = now - timedelta(days=365 * num)
            else:
                print(f"[DEBUG] Unknown time unit: {unit}, returning original text")
                return pubtext
            result = dt.astimezone(timezone.utc).isoformat()
            print(f"[DEBUG] Parsed relative time '{s}' as: {result}")
            return result

        # Absolute like 'Dec 3, 2025' or 'Sep 4, 2025'
        m2 = ABS_MONTH_DAY_YEAR.match(s)
        if m2:
            mon = m2.group('mon')[:3].title()
            day = int(m2.group('day'))
            year = int(m2.group('year'))
            # Map full month names too
            month_num = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
            if mon in month_num:
                dt = datetime(year, month_num[mon], day, tzinfo=timezone.utc)
                result = dt.isoformat()
                print(f"[DEBUG] Parsed absolute time '{s}' as: {result}")
                return result

        # ISO-like strings
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            result = dt.astimezone(timezone.utc).isoformat()
            print(f"[DEBUG] Parsed ISO time '{s}' as: {result}")
            return result
        except Exception:
            pass

        # RFC-2822 / HTTP-date forms like 'Tue, 27 Jan 2026 17:08:30 GMT'
        try:
            dt = email.utils.parsedate_to_datetime(s)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                result = dt.astimezone(timezone.utc).isoformat()
                print(f"[DEBUG] Parsed RFC-2822 time '{s}' as: {result}")
                return result
        except Exception:
            pass

        # Some pages show just '6 days ago' or 'Today' or 'Yesterday'
        s_low = s.lower()
        if s_low.startswith('today'):
            dt = datetime.now(timezone.utc)
            result = dt.isoformat()
            print(f"[DEBUG] Parsed 'today' as: {result}")
            return result
        if s_low.startswith('yesterday'):
            dt = (datetime.now(timezone.utc) - timedelta(days=1))
            result = dt.isoformat()
            print(f"[DEBUG] Parsed 'yesterday' as: {result}")
            return result

        # Return the original text if no parsing worked
        print(f"[DEBUG] Could not parse '{s}', returning original text")
        return pubtext

    async def extract_pine_source(self, script_url: str, isolated: bool = False) -> dict:
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
            'is_library': False,
        }
        
        try:
            # If positional click mode is enabled, inject the copy-capture init script before navigation
            if getattr(self, 'positional_click', False):
                try:
                    await self.page.add_init_script(r"""() => {
                        window.__copied__ = '';
                        document.addEventListener('copy', function(e){ try { window.__copied__ = (e.clipboardData && e.clipboardData.getData('text/plain')) || document.getSelection().toString(); } catch(e){} }, true);
                        try {
                            const origWrite = navigator.clipboard && navigator.clipboard.writeText;
                            if (origWrite) {
                                navigator.clipboard.writeText = async function(t){ try{ window.__copied__ = t || ''; }catch(e){}; return origWrite.call(this, t); };
                            } else {
                                navigator.clipboard = { writeText: async function(t){ try{ window.__copied__ = t || ''; }catch(e){}; } };
                            }
                        } catch(e){}
                    }""")
                except Exception:
                    pass

            response = await self.page.goto(script_url, wait_until='domcontentloaded', timeout=30000)
            if not response or response.status >= 400:
                result['error'] = f"HTTP {response.status if response else 'No response'}"
                print(f"[DEBUG] extract_pine_source early exit: {result['error']}", flush=True)
                return result

            # Human-like behavior: wait and move mouse. When running in isolated single-script mode (batch->single flow)
            # skip human-like interactions to match single-script behavior exactly.
            if not isolated:
                await self.page.wait_for_timeout(random.randint(1500, 2500))
                await self.handle_cookie_consent()
                await self._human_like_mouse_move()
                if not getattr(self, 'positional_click', False):
                    await self._human_like_scroll()
                else:
                    if getattr(self, 'debug_pages', False):
                        print('   [debug] Skipping human-like scroll because positional click is enabled')
            else:
                # Shorter, deterministic delay for isolated mode and skip random mouse/scroll
                await self.page.wait_for_timeout(300)
                if getattr(self, 'debug_pages', False):
                    print('   [debug] Running in isolated mode: skipped human-like mouse/scroll')
            
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

            # First try the enhanced exact publish date extraction
            exact_published_date = await self.extract_exact_publish_date()

            # Debug output to see what dates we're getting
            print(f"[DEBUG] Original published_date: {extended_meta.get('published_date', '')}")
            print(f"[DEBUG] Exact published_date: {exact_published_date}")

            # Merge extended metadata
            # Use the exact date if available, otherwise fall back to the original method
            result['published_date'] = exact_published_date or extended_meta.get('published_date', '')
            # Normalize published_date to ISO+TZ when possible
            try:
                pd = result.get('published_date')
                if pd:
                    from email.utils import parsedate_to_datetime
                    def _normalize_pub(s):
                        s = s.strip()
                        # try iso
                        try:
                            dt = datetime.fromisoformat(s)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            return dt.astimezone(timezone.utc).isoformat()
                        except Exception:
                            pass
                        # try rfc
                        try:
                            dt = parsedate_to_datetime(s)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            return dt.astimezone(timezone.utc).isoformat()
                        except Exception:
                            pass
                        # try simple month day, year
                        m = ABS_MONTH_DAY_YEAR.match(s)
                        if m:
                            mon = m.group('mon')[:3].title()
                            day = int(m.group('day'))
                            year = int(m.group('year'))
                            if mon in MONTHS:
                                dt = datetime(year, MONTHS[mon], day, tzinfo=timezone.utc)
                                return dt.isoformat()
                        # relative times like '6 days ago'
                        m2 = REL_RE.search(s)
                        if m2:
                            num = int(m2.group('num'))
                            unit = m2.group('unit').lower()
                            now = datetime.utcnow().replace(tzinfo=timezone.utc)
                            if unit.startswith('second'):
                                dt = now - timedelta(seconds=num)
                            elif unit.startswith('minute'):
                                dt = now - timedelta(minutes=num)
                            elif unit.startswith('hour'):
                                dt = now - timedelta(hours=num)
                            elif unit.startswith('day'):
                                dt = now - timedelta(days=num)
                            elif unit.startswith('week'):
                                dt = now - timedelta(weeks=num)
                            elif unit.startswith('month'):
                                dt = now - timedelta(days=30*num)
                            elif unit.startswith('year'):
                                dt = now - timedelta(days=365*num)
                            else:
                                dt = None
                            if dt:
                                return dt.astimezone(timezone.utc).isoformat()
                        return None
                    norm = _normalize_pub(pd)
                    if norm:
                        result['published_date'] = norm
            except Exception:
                pass

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
                                        # Ensure overlays are cleared
                                await self.handle_overlays()
                                if getattr(self, 'positional_click', False):
                                    # In positional mode, avoid scrolling; dispatch an in-page click event to prevent layout jumps
                                    try:
                                        await t.first.evaluate("el => { try { el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true})); } catch(e){} }")
                                        await self.page.wait_for_timeout(700)
                                        if getattr(self, 'debug_pages', False):
                                            print(f"   [debug] Dispatched JS click to Source tab using selector: {s}")
                                    except Exception:
                                        # Fallback to Playwright click if dispatch fails
                                        await t.first.click()
                                        await self.page.wait_for_timeout(700)
                                else:
                                    await t.first.evaluate('el => el.scrollIntoView({block: "center"})')
                                    await t.first.click()
                                    await self.page.wait_for_timeout(600)
                                if getattr(self, 'debug_pages', False):
                                    print(f"   [debug] Clicked Source code tab using selector: {s}")

                                # Immediately after opening the Source tab, try a positional click
                                if getattr(self, 'positional_click', False):
                                    try:
                                        if getattr(self, 'debug_pages', False):
                                            print('   [debug] Attempting immediate positional click after Source tab')
                                        # Ensure overlays are removed *before* we freeze scrolling so they don't trigger scroll/overlays
                                        try:
                                            await self.handle_overlays()
                                        except Exception:
                                            pass

                                        # Prevent unwanted page scrolling while we probe the code container.
                                        # Use a stronger lock: poll until scroll is stable then set body to position:fixed
                                        try:
                                            await self.page.evaluate('''() => {
                                                try {
                                                    // capture current scroll
                                                    const y = window.scrollY || document.scrollingElement.scrollTop || 0;
                                                    // store originals to restore later
                                                    window._orig_scroll_lock = {
                                                        overflow: document.body.style.overflow || '',
                                                        position: document.body.style.position || '',
                                                        top: document.body.style.top || '',
                                                        scrollY: y
                                                    };
                                                    // lock the scroll in place by fixing body position
                                                    document.body.style.overflow = 'hidden';
                                                    document.body.style.position = 'fixed';
                                                    document.body.style.top = `-${y}px`;
                                                } catch(e){}
                                            }''')
                                            # Wait for scroll to settle (no changes in scrollY)
                                            stable = False
                                            last_y = None
                                            for _ in range(10):
                                                try:
                                                    cur = await self.page.evaluate('() => window.scrollY || document.scrollingElement.scrollTop || 0')
                                                except Exception:
                                                    cur = None
                                                if cur is None:
                                                    break
                                                if last_y is not None and abs(cur - last_y) <= 1:
                                                    stable = True
                                                    break
                                                last_y = cur
                                                await self.page.wait_for_timeout(80)
                                            if getattr(self, 'debug_pages', False):
                                                print(f"   [debug] Scroll lock applied (stable={stable}, y={last_y})")
                                        except Exception:
                                            pass

                                        # Take a screenshot to inspect layout before clicking (only when debug_pages enabled)
                                        try:
                                            if getattr(self, 'debug_pages', False):
                                                dbg_dir = self.output_dir / 'debug_positional'
                                                dbg_dir.mkdir(parents=True, exist_ok=True)
                                                ss_path = dbg_dir / f"{result.get('script_id')}_before_pos_click.png"
                                                await self.page.screenshot(path=str(ss_path))
                                                print(f"   [debug] Saved positional pre-click screenshot: {ss_path}")
                                        except Exception:
                                            pass

                                        # Find bounding box and log it
                                        try:
                                            box = await self.page.evaluate('''() => {
                                                try {
                                                    const nodes = Array.from(document.querySelectorAll('div, section, pre'));
                                                    for (const n of nodes) {
                                                        try {
                                                            const t = (n.textContent || '');
                                                            if (t.includes('//@version') || t.includes('indicator(') || t.includes('library(') || t.includes('plot(')) {
                                                                const r = n.getBoundingClientRect();
                                                                return {x: r.x, y: r.y, width: r.width, height: r.height};
                                                            }
                                                        } catch(e){}
                                                    }
                                                } catch(e){}
                                                return null;
                                            }''')
                                            if box and getattr(self, 'debug_pages', False):
                                                print(f"   [debug] Code container bbox: x={box['x']:.1f}, y={box['y']:.1f}, w={box['width']:.1f}, h={box['height']:.1f}")
                                            # Explicitly scroll the code container into view (center) to avoid site-driven scroll jumps
                                            try:
                                                await self.page.evaluate('(b) => { window.scrollTo({ top: Math.max(0, b.y - 60), left: Math.max(0, b.x - 20), behavior: "instant" }); }', box)
                                                await self.page.wait_for_timeout(120)
                                            except Exception:
                                                pass
                                        except Exception:
                                            box = None

                                        # Try positional click and then restore overflow
                                        try:
                                            pos_res = await self._try_positional_click_extraction()
                                            if pos_res:
                                                source_code = pos_res
                                                if getattr(self, 'debug_pages', False):
                                                    print(f"   [debug] Immediate positional capture length: {len(source_code)}")
                                        finally:
                                            try:
                                                await self.page.evaluate('''() => { try { const s = window._orig_scroll_lock || {}; if (s && s.top !== undefined) { document.body.style.position = s.position || ''; document.body.style.top = s.top || ''; } document.body.style.overflow = (s && s.overflow !== undefined) ? s.overflow : ''; delete window._orig_scroll_lock; }''')
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass

                                break
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                pass


            # Probeer tot 3 keer clipboard/copy-knop extractie
            max_retries = 3
            source_code = ''
            for attempt in range(1, max_retries + 1):
                # Ensure overlays removed before each attempt
                try:
                    await self.handle_overlays()
                except Exception:
                    pass

                # Attempt to click copy buttons and read clipboard / in-page captures
                try:
                    source_code = ''
                    # If enabled, try a fixed-position click first (fast, fragile but often reliable when layout is stable)
                    if getattr(self, 'positional_click', False):
                        try:
                            source_code = await self._try_positional_click_extraction()
                            if getattr(self, 'debug_pages', False):
                                print(f"   [debug] Positional click capture length: {len(source_code) if source_code else 0}")
                        except Exception:
                            source_code = ''

                    # Fallback to the standard selector-based copy-button extraction
                    if not source_code:
                        # Clear clipboard before attempting selector-based extraction to avoid stale content
                        try:
                            await self.page.evaluate('async () => { try { if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(''); } catch(e){} }')
                            if getattr(self, 'debug_pages', False):
                                print('   [debug] Cleared clipboard before selector-based extraction')
                        except Exception:
                            pass
                        try:
                            source_code = await self._try_copy_button_extraction()
                        except Exception:
                            source_code = ''
                except Exception:
                    source_code = ''

                if source_code:
                    # Mark that this source came directly from the copy-to-clipboard flow and
                    # keep the raw captured value so we can save it byte-for-byte later.
                    result['source_origin'] = 'clipboard'
                    result['source_raw'] = source_code

                    # Basic verification: compare to the visible source in the page (if available)
                    try:
                        page_visible = await self._try_source_tab_extraction()
                    except Exception:
                        page_visible = ''

                    def _snippet_matches(a: str, b: str) -> bool:
                        if not a or not b:
                            return True
                        a_snip = a.strip()[:200]
                        b_snip = b.strip()[:200]
                        if not a_snip:
                            return True
                        # Accept if page snippet appears in clipboard or vice versa
                        return (a_snip in b) or (b_snip in a)

                    if not _snippet_matches(page_visible, source_code):
                        # Detected a mismatch: clipboard content doesn't look like page source -> stale
                        result['error'] = 'stale_clipboard'
                        if getattr(self, 'debug_pages', False):
                            print('   [debug] Detected stale clipboard (clipboard != visible source)')
                        # Try to clear clipboard and retry
                        try:
                            await self.page.evaluate('''async () => { try { if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(''); } catch(e){} }''')
                        except Exception:
                            pass
                        source_code = ''
                        continue

                    # Hash and deduplicate: if this clipboard payload was already used for a different URL,
                    # treat as stale so caller can retry.
                    try:
                        import hashlib
                        h = hashlib.sha256(source_code.encode('utf-8')).hexdigest()
                        owner = self._seen_clipboard_hashes.get(h)
                        if owner and owner != script_url:
                            result['error'] = 'stale_clipboard'
                            if getattr(self, 'debug_pages', False):
                                print(f"   [debug] Detected duplicate clipboard hash used earlier by {owner}")
                            # clear clipboard and retry
                            try:
                                await self.page.evaluate('''async () => { try { if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(''); } catch(e){} }''')
                            except Exception:
                                pass
                            source_code = ''
                            continue
                        # record first owner
                        if not owner:
                            self._seen_clipboard_hashes[h] = script_url
                    except Exception:
                        pass

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
                                            # Immediately attempt positional click after opening Source (recovery path)
                                            if getattr(self, 'positional_click', False):
                                                try:
                                                    if getattr(self, 'debug_pages', False):
                                                        print('   [debug] Attempting immediate positional click after Source tab (recovery)')
                                                    try:
                                                        await self.page.evaluate("() => { document._orig_overflow = document.body.style.overflow || ''; document.body.style.overflow = 'hidden'; }")
                                                    except Exception:
                                                        pass
                                                    try:
                                                        if getattr(self, 'debug_pages', False):
                                                            dbg_dir = self.output_dir / 'debug_positional'
                                                            dbg_dir.mkdir(parents=True, exist_ok=True)
                                                            ss_path = dbg_dir / f"{result.get('script_id')}_before_pos_click_recovery.png"
                                                            await self.page.screenshot(path=str(ss_path))
                                                            print(f"   [debug] Saved positional pre-click screenshot (recovery): {ss_path}")
                                                    except Exception:
                                                        pass
                                                    try:
                                                        pos_res = await self._try_positional_click_extraction()
                                                        if pos_res:
                                                            source_code = pos_res
                                                            if getattr(self, 'debug_pages', False):
                                                                print(f"   [debug] Immediate positional capture length (recovery): {len(source_code)}")
                                                    finally:
                                                        try:
                                                            await self.page.evaluate("() => { if (document._orig_overflow !== undefined) document.body.style.overflow = document._orig_overflow; delete document._orig_overflow; }")
                                                        except Exception:
                                                            pass
                                                except Exception:
                                                    pass
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
                                            # Immediately attempt positional click after opening Source (post-restart path)
                                            if getattr(self, 'positional_click', False):
                                                try:
                                                    if getattr(self, 'debug_pages', False):
                                                        print('   [debug] Attempting immediate positional click after Source tab (post-restart)')
                                                    try:
                                                        await self.page.evaluate("() => { document._orig_overflow = document.body.style.overflow || ''; document.body.style.overflow = 'hidden'; }")
                                                    except Exception:
                                                        pass
                                                    try:
                                                        if getattr(self, 'debug_pages', False):
                                                            dbg_dir = self.output_dir / 'debug_positional'
                                                            dbg_dir.mkdir(parents=True, exist_ok=True)
                                                            ss_path = dbg_dir / f"{result.get('script_id')}_before_pos_click_postrestart.png"
                                                            await self.page.screenshot(path=str(ss_path))
                                                            print(f"   [debug] Saved positional pre-click screenshot (post-restart): {ss_path}")
                                                    except Exception:
                                                        pass
                                                    try:
                                                        pos_res = await self._try_positional_click_extraction()
                                                        if pos_res:
                                                            source_code = pos_res
                                                            if getattr(self, 'debug_pages', False):
                                                                print(f"   [debug] Immediate positional capture length (post-restart): {len(source_code)}")
                                                    finally:
                                                        try:
                                                            await self.page.evaluate("() => { if (document._orig_overflow !== undefined) document.body.style.overflow = document._orig_overflow; delete document._orig_overflow; }")
                                                        except Exception:
                                                            pass
                                                except Exception:
                                                    pass
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

            # Detect script kind: library / strategy / indicator
            try:
                # Prefer normalized visible source, but fall back to raw clipboard payload if needed
                raw_to_check = result.get('source_code') or result.get('source_raw') or ''
                src_low = raw_to_check.lower()
                result['is_library'] = ('library(' in src_low) or ('\nlibrary(' in src_low) or (' library ' in src_low)
                result['is_strategy'] = 'strategy(' in src_low
                # If neither library nor strategy, treat as indicator by default
            except Exception:
                result['is_library'] = result.get('is_library', False)
                result['is_strategy'] = result.get('is_strategy', False)

            print(f"[DEBUG] extract_pine_source success: script_id={result.get('script_id')} title={result.get('title')} source_len={len(result.get('source_code') or '')} is_library={result.get('is_library')} is_strategy={result.get('is_strategy')}", flush=True)

            return result
            
        except PlaywrightTimeoutError:
            result['error'] = 'Timeout'
            print(f"[DEBUG] extract_pine_source timeout", flush=True)
            return result
        except Exception as e:
            result['error'] = str(e)[:100]
            return result

    def _normalize_source(self, source: str) -> str:
        """Normalize source code encoding and whitespace."""
        if not source or not isinstance(source, str):
            return source or ''
        # Handle unicode escape sequences like '\n', '\t', or '\uXXXX'
        if '\\n' in source or '\\t' in source or '\\u' in source:
            try:
                source = codecs.decode(source, 'unicode_escape')
            except Exception:
                source = source.replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t')
                source = source.replace('\"', '"').replace(r'\/', '/')
        # Normalize line endings
        source = source.replace('\r\n', '\n').replace('\r', '\n')
        return source

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
                        if getattr(self, 'fast_mode', False):
                            await self.page.wait_for_timeout(random.randint(400, 800))
                        else:
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

        # 2) Iterate visible copy buttons (bottom-up), click and try to read clipboard / in-page captures
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
                            await self.page.wait_for_timeout(300 if getattr(self, 'fast_mode', False) else 500)
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

    async def _try_positional_click_extraction(self) -> str:
        """Try to click a fixed relative position inside the visible code container and read the copied text.
        This is faster but brittle — use only when layout is stable or when enabled via --positional-click."""
        try:
            # Find a candidate container that looks like the code block and return its bounding box
            box = await self.page.evaluate('''() => {
                try {
                    const nodes = Array.from(document.querySelectorAll('div, section, pre'));
                    for (const n of nodes) {
                        try {
                            const t = (n.textContent || '');
                            if (t.includes('//@version') || t.includes('indicator(') || t.includes('library(') || t.includes('plot(')) {
                                const r = n.getBoundingClientRect();
                                return {x: r.x, y: r.y, width: r.width, height: r.height};
                            }
                        } catch(e){}
                    }
                } catch(e){}
                return null;
            }''')

            if not box:
                return ''

            # Wait a short moment (polling) for the code container to populate; helps avoid clicking wrong buttons
            try:
                for _ in range(10):
                    txt_len = await self.page.evaluate('(b) => { try { const n = document.elementFromPoint(b.x + 10, b.y + 10); return (n && n.textContent) ? n.textContent.length : 0;}', box)
                    if txt_len and txt_len > 12:
                        break
                    await self.page.wait_for_timeout(50)
            except Exception:
                pass

            # Try to find an actual copy button *inside* the container first (more reliable than raw offsets)
            try:
                btn_rect = await self.page.evaluate('''(box) => {
                    try {
                        const sel = ['button[aria-label*="copy"]', 'button[title*="Copy"]', '.copy-to-clipboard', '[data-qa-id*="copy"]', '.tv-copy', 'button'];
                        const blacklist = ['free','trial','upgrade','subscribe','login','signup','sign in','buy'];
                        // find the element which is inside the box and looks like a copy control
                        for (const s of sel) {
                            const nodes = Array.from(document.querySelectorAll(s));
                            for (const n of nodes) {
                                try {
                                    const r = n.getBoundingClientRect();
                                    if (r.width > 6 && r.height > 6 && r.x >= box.x - 2 && (r.x + r.width) <= (box.x + box.width + 2) && r.y >= box.y - 2 && (r.y + r.height) <= (box.y + box.height + 2)) {
                                        // basic label blacklist check
                                        const label = ((n.getAttribute('aria-label')||'') + ' ' + (n.getAttribute('title')||'') + ' ' + (n.textContent||'')).toLowerCase();
                                        let skip = false;
                                        for (const b of blacklist) { if (label.includes(b)) { skip = true; break; } }
                                        if (!skip) return {x: r.x, y: r.y, width: r.width, height: r.height};
                                    }
                                    // also accept small buttons near top-right region (but only for candidates we explicitly matched)
                                    const nearRight = (r.x >= (box.x + box.width - 120) && r.y <= (box.y + 80));
                                    if (nearRight && r.width > 6 && r.height > 6) {
                                        const label = ((n.getAttribute('aria-label')||'') + ' ' + (n.getAttribute('title')||'') + ' ' + (n.textContent||'')).toLowerCase();
                                        let bad = false;
                                        for (const b of blacklist) { if (label.includes(b)) { bad = true; break; } }
                                        if (!bad) return {x: r.x, y: r.y, width: r.width, height: r.height};
                                    }
                                } catch(e){}
                            }
                        }
                        // Extra pass: look for generic <button> elements only if they *look* like copy controls
                        try {
                            const btns = Array.from(document.querySelectorAll('button'));
                            for (const n of btns) {
                                try {
                                    const r = n.getBoundingClientRect();
                                    if (r.width <= 6 || r.height <= 6) continue;
                                    // aggregate text-like labels for heuristic
                                    const label = ((n.getAttribute('aria-label')||'') + ' ' + (n.getAttribute('title')||'') + ' ' + (n.textContent||'') + ' ' + (n.innerHTML||'')).toLowerCase();
                                    const nearRight = (r.x >= (box.x + box.width - 120) && r.y <= (box.y + 80));
                                    const looksLikeCopy = /copy|kopi[eë]|clipboard|kopie/i.test(label);
                                    const hasSvg = !!n.querySelector('svg');
                                    // blacklist check to avoid hitting promotional buttons like 'free_trial'
                                    let skip = false;
                                    for (const b of blacklist) { if (label.includes(b)) { skip = true; break; } }
                                    if (skip) continue;
                                    if ((looksLikeCopy || (hasSvg && nearRight)) && r.x >= box.x - 2 && (r.x + r.width) <= (box.x + box.width + 2) && r.y >= box.y - 2 && (r.y + r.height) <= (box.y + box.height + 2)) {
                                        return {x: r.x, y: r.y, width: r.width, height: r.height};
                                    }
                                } catch(e){}
                            }
                        } catch(e){}
                    } catch(e){}
                    return null;
                }''', box)
            except Exception:
                btn_rect = None

            if btn_rect:
                # Gebruik de knop als hij gevonden is (zoals voorheen)
                try:
                    await self.handle_overlays()
                except Exception:
                    pass
                # Only scroll into view if positional click mode is NOT enabled (user requested no scroll)
                if not getattr(self, 'positional_click', False):
                    try:
                        await self.page.evaluate('''(b) => { const el = document.elementFromPoint(b.x + b.width/2, b.y + b.height/2); if (el && el.scrollIntoView) el.scrollIntoView({block:'center'}); }''', btn_rect)
                    except Exception:
                        pass
                else:
                    if getattr(self, 'debug_pages', False):
                        print('   [debug] Skipping scrollIntoView due to positional_click mode')
                click_x = btn_rect['x'] + btn_rect['width'] / 2
                click_y = btn_rect['y'] + btn_rect['height'] / 2
                if getattr(self, 'debug_pages', False):
                    print(f"   [debug] Using inner-button rect for positional click at ({click_x:.1f},{click_y:.1f})")
            else:
                # Horizontale click-methode: klik altijd rechtsboven in het codeblok, binnen de viewport
                try:
                    await self.handle_overlays()
                except Exception:
                    pass
                # Kies een X-positie 40px van de rechterkant, Y-positie 30px onder de bovenkant
                click_x = box['x'] + max(16, box['width'] - 40)
                click_y = box['y'] + 30
                # Only perform fallback scroll if positional mode is not requested
                if not getattr(self, 'positional_click', False):
                    try:
                        await self.page.evaluate('(x, y) => { window.scrollTo({top: Math.max(0, y-80), left: Math.max(0, x-200), behavior: "instant"}); }', click_x, click_y)
                        await self.page.wait_for_timeout(50)
                    except Exception:
                        pass
                else:
                    if getattr(self, 'debug_pages', False):
                        print('   [debug] Skipping fallback scroll due to positional_click mode')
                if getattr(self, 'debug_pages', False):
                    print(f"   [debug] Using fallback horizontal click at ({click_x:.1f},{click_y:.1f})")
            # Clear clipboard (avoid stale clipboard causing false positives) then perform the click and wait briefly
            try:
                await self.page.evaluate('async () => { try { if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(''); } catch(e){} }')
            except Exception:
                pass

            # DOM-click attempt: try clicking copy controls inside the code container (mirror dump-copy) before mouse clicks
            try:
                dom_cb = await self.page.evaluate(r'''async (box) => {
                    function looksLikeCopyBtn(el){
                        const label = ((el.getAttribute && (el.getAttribute('aria-label')||'')) + ' ' + (el.getAttribute && (el.getAttribute('title')||'')) + ' ' + (el.textContent||'')).toLowerCase();
                        if (label.includes('import')) return false;
                        return /copy|kopi|clipboard/.test(label) || (el.className && /copy|clipboard/.test(String(el.className).toLowerCase()));
                    }
                    const candidates = Array.from(document.querySelectorAll('button, [role="button"], .copy-to-clipboard, [data-qa-id*="copy"], [class*="copy"], .tv-copy'));
                    for (const c of candidates){
                        try {
                            const r = c.getBoundingClientRect();
                            if (r.width < 6 || r.height < 6) continue;
                            const insideBox = (r.x >= box.x - 2 && (r.x + r.width) <= (box.x + box.width + 2) && r.y >= box.y - 2 && (r.y + r.height) <= (box.y + box.height + 2));
                            const nearRight = (r.x >= (box.x + box.width - 320) && r.y <= (box.y + 120));
                            if (!insideBox && !nearRight) continue;
                            // Skip if nearby code looks like an import-only snippet
                            const dialog = c.closest('[role="dialog"]')||c.closest('div')||document.body;
                            const code = dialog.querySelector('pre, code, textarea, [class*="code"], [class*="source"]');
                            const nearby = (code? (code.value||code.textContent||'') : '').trim().toLowerCase();
                            if (nearby.startsWith('import') && !(nearby.includes('//@version') || nearby.includes('indicator(') || nearby.includes('library(') || nearby.includes('strategy(') || nearby.includes('plot('))) continue;
                            if (!looksLikeCopyBtn(c)) continue;
                            let captured='';
                            const handler = (e)=>{ try{ captured=(e.clipboardData && e.clipboardData.getData('text/plain'))||document.getSelection().toString(); }catch(e){} };
                            document.addEventListener('copy', handler, {once:true});
                            try{ c.click(); }catch(e){ try{ c.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true})); }catch(e){} }
                            const start=Date.now();
                            while((Date.now()-start)<1500){ if (captured) break; await new Promise(r=>setTimeout(r,100)); }
                            try{ document.removeEventListener('copy', handler); }catch(e){}
                            if (!captured && navigator.clipboard && navigator.clipboard.readText){ try{ captured = await navigator.clipboard.readText(); }catch(e){} }
                            if (captured && (captured.includes('//@version') || captured.includes('indicator(') || captured.includes('library(') || captured.includes('plot('))) return captured;
                        }catch(e){}
                    }
                    return '';
                }''', box)
                if dom_cb and ("//@version" in dom_cb or "indicator(" in dom_cb or "library(" in dom_cb or "plot(" in dom_cb):
                    return dom_cb
            except Exception:
                pass

            # Try clicking, but first remove/hide any overlays that may intercept the pointer.
            clicked = False
            for attempt in range(4):
                try:
                    # Hide common interceptors near click point and globally
                    try:
                        # Only hide overlay elements that do NOT overlap the code container (preserve source header/copy UI)
                        await self.page.evaluate('''(x,y,box) => {
                            const toHide = ["#credential_picker_container", ".apply-overflow-tooltip", "#overlap-manager-root", "[data-qa-id=\\"overlap-manager-root\\"]"];
                            toHide.forEach(s=>{ document.querySelectorAll(s).forEach(e => { try{ e.style.display = "none"; e.style.pointerEvents = "none"; }catch(e){} }); });
                            const els = document.elementsFromPoint(x,y);
                            for (const e of els) {
                                try {
                                    const t = (e.textContent||" ").toLowerCase();
                                    if (t.includes('get started') || t.includes('free trial') || t.includes('upgrade') || t.includes('subscribe')) {
                                        const r = e.getBoundingClientRect();
                                        const overlapsBox = !(r.right < box.x || r.left > (box.x + box.width) || r.bottom < box.y || r.top > (box.y + box.height));
                                        if (!overlapsBox) { e.style.display='none'; e.style.pointerEvents='none'; }
                                    }
                                } catch(e){}
                            }
                        }''', click_x, click_y, box)
                    except Exception:
                        pass

                    if getattr(self, 'positional_click', False):
                        # In positional mode we avoid scrolling and use in-page dispatch click at the coordinate to avoid layout shifts
                        try:
                            await self.page.evaluate('(x,y) => { try { const els = document.elementsFromPoint(x,y); if(els && els.length>0){ try{ els[0].dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true})); }catch(e){} return; } } catch(e){} }', click_x, click_y)
                            clicked = True
                            break
                        except Exception as e:
                            if getattr(self, 'debug_pages', False):
                                print(f"   [debug] Positional JS dispatch attempt {attempt+1} failed: {e}")
                            await self.page.wait_for_timeout(200)
                            continue
                    else:
                        # Scroll a little to ensure the click point is in view and not blocked
                        try:
                            await self.page.evaluate('(x,y) => { const els = document.elementsFromPoint(x,y); if(els && els.length>0) return; window.scrollTo({top: Math.max(0, y-80), left: Math.max(0, x-20), behavior: "instant"}); }', click_x, click_y)
                            await self.page.wait_for_timeout(50)
                        except Exception:
                            pass
                        await self.page.mouse.click(click_x, click_y)
                        clicked = True
                        break
                except Exception as e:
                    if getattr(self, 'debug_pages', False):
                        print(f"   [debug] Positional click attempt {attempt+1} failed: {e}")
                    # As a fallback, try a forced click after hiding overlays
                    if getattr(self, 'positional_click', False):
                        try:
                            await self.page.evaluate('(x,y) => { try { const els = document.elementsFromPoint(x,y); if(els && els.length>0){ try{ els[0].dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true})); }catch(e){} return; } } catch(e){} }', click_x, click_y)
                            clicked = True
                            break
                        except Exception as e2:
                            if getattr(self, 'debug_pages', False):
                                print(f"   [debug] Positional JS force attempt failed: {e2}")
                            await self.page.wait_for_timeout(200)
                            continue
                    else:
                        try:
                            await self.page.mouse.click(click_x, click_y, force=True)
                            clicked = True
                            break
                        except Exception as e2:
                            if getattr(self, 'debug_pages', False):
                                print(f"   [debug] Force click attempt failed: {e2}")
                            await self.page.wait_for_timeout(200)
                            continue

            if not clicked:
                return ''

            await self.page.wait_for_timeout(800 if getattr(self, 'fast_mode', False) else 1000)

            # Read any in-page capture helper first
            try:
                tmp = await self.page.evaluate('''() => {
                    if (window.__copied__ && typeof window.__copied__ === 'string') return window.__copied__;
                    if (window.__copied_source__ && typeof window.__copied_source__ === 'string') return window.__copied_source__;
                    const ta = document.querySelector('textarea'); if (ta && ta.value) return ta.value;
                    const inp = document.querySelector('input[type="text"]'); if (inp && inp.value) return inp.value;
                    const sel = (window.getSelection && window.getSelection().toString()) || '';
                    return sel || '';
                }''')
                if tmp and ("//@version" in tmp or "indicator(" in tmp or "library(" in tmp or "plot(" in tmp):
                    return tmp
            except Exception:
                pass

            # Fallback to reading navigator.clipboard
            try:
                cb = await self.page.evaluate('navigator.clipboard && navigator.clipboard.readText ? navigator.clipboard.readText() : ""')
                if cb and ("//@version" in cb or "indicator(" in cb or "library(" in cb or "plot(" in cb):
                    return cb
            except Exception:
                pass

        except Exception:
            return ''

        return ''

    async def dump_copy_diagnostics(self, url: str):
        """Visit a single script URL and print diagnostics for copy-button capture attempts."""
        await self.setup()
        try:
            # Extract the exact publish date before injecting copy-capture helpers
            await self.page.goto(url, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_timeout(800)

            # Extract exact publish date for use in header
            exact_published_date = await self.extract_exact_publish_date()
            print(f"[DEBUG] Exact published date for header: {exact_published_date}")

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
                    const mo = new MutationObserver((muts) => { for (const m of muts) { for (const n of Array.from(m.addedNodes || [])) { try { const t = (n && n.textContent) ? String(n.textContent) : ''; if (t && (t.includes('//@version') || t.includes('indicator(') || t.includes('strategy(') || t.includes('library(') || t.includes('plot('))) { window.__cv.mutations.push(t); window.__cv.logs.push({type:'mutation', text:t, time:Date.now()}); } } catch(e){} } }); mo.observe(document, { childList: true, subtree: true }); window.__cv._mo = true;
                } catch(e){}
                const origAddEventListener = EventTarget.prototype.addEventListener;
                EventTarget.prototype.addEventListener = function(type, ...rest){ if (type && (type.toLowerCase().includes('copy') || type.toLowerCase().includes('clipboard'))) { try{ window.__cv.logs.push({type:'addEventListener', event:type, target:this && this.tagName, time:Date.now()}); }catch(e){} } return origAddEventListener.call(this, type, ...rest); };
            }''')
            print('   [debug] Injected copy-capture init script')
            print(f"Diagnostics: visiting {url}")

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
                for (const sel of btnSelectors){ const nodes=Array.from(document.querySelectorAll(sel)); nodes.forEach((b,i)=>{ try { const btnText = (b.innerText||'').toLowerCase(); const dialog=b.closest('[role="dialog"]')||b.closest('div')||document.body; const code=dialog.querySelector('pre, code, textarea, [class*="code"], [class*="source"]'); const nearbyText = (code? (code.value||code.textContent||'') : '').trim(); const lowNearby = (nearbyText||'').toLowerCase(); // skip if button itself or nearby code indicates an Import-only snippet
                            if (btnText.includes('import')) return; if (lowNearby.startsWith('import') && !(lowNearby.includes('//@version') || lowNearby.includes('indicator(') || lowNearby.includes('library(') || lowNearby.includes('strategy(') || lowNearby.includes('plot('))) return; let struct = [];
                            try { let candidate = dialog.querySelector('div'); let container = candidate || dialog; try { let p=container; while(p && p.parentElement && container.children.length < 10){ p = p.parentElement; container = p; } } catch(e){}
                                struct = Array.from(container.children).slice(0,10).map(c => ({tag: c.tagName, text: (c.textContent||'').trim().slice(0,200)})); } catch(e){}
                            found.buttons.push({selector: sel, idx:i, text: (b.innerText||'').slice(0,120), nearby: (code? (code.value||code.textContent||'').slice(0,200):''), structureSample: struct}); }catch(e){} }); }
                async function tryClick(b){ window.__copied__=''; const handler=(e)=>{ try{ window.__copied__=(e.clipboardData&&e.clipboardData.getData('text/plain'))||'';}catch{} }; document.addEventListener('copy', handler, {once:true}); try{ b.click(); }catch{}; const start=Date.now(); while((Date.now()-start)<2000){ await new Promise(r=>setTimeout(r,150)); if(window.__copied__) break; } try{ document.removeEventListener('copy', handler); }catch{}; let cb=window.__copied__||''; try{ if(!cb && navigator.clipboard && navigator.clipboard.readText) cb=await navigator.clipboard.readText(); }catch{}; return cb; }
                const caps=[]; const btns=Array.from(document.querySelectorAll(btnSelectors.join(',')));
                for (const b of btns){ try{ const t=(b.innerText||'').toLowerCase(); const dialog=b.closest('[role="dialog"]')||b.closest('div')||document.body; const code=dialog.querySelector('pre, code, textarea, [class*="code"], [class*="source"]'); const nearby=(code? (code.value||code.textContent||'') : '').trim().toLowerCase(); if(t.includes('import') || (nearby.startsWith('import') && !(nearby.includes('//@version') || nearby.includes('indicator(') || nearby.includes('library(') || nearby.includes('strategy(') || nearby.includes('plot(')))) continue; caps.push(await tryClick(b)); }catch(e){} }
                return {found: found, captures: caps};
            }''')

            # Helper to sanitize arbitrary text for consoles that don't support full Unicode
            import sys
            def _sanitize(x):
                if x is None:
                    return ''
                s = str(x)
                try:
                    enc = sys.stdout.encoding or 'utf-8'
                    return s.encode(enc, errors='backslashreplace').decode(enc, errors='replace')
                except Exception:
                    return s.encode('utf-8', errors='backslashreplace').decode('ascii', errors='replace')

            # print results (sanitized to avoid UnicodeEncodeError on cp1252 consoles)
            for a in data.get('found', {}).get('attrs', []):
                print(f"[ATTR] {_sanitize(a.get('attr'))} sample: {_sanitize(a.get('sample'))}")
            for b in data.get('found', {}).get('buttons', []):
                print(f"[BUTTON] {_sanitize(b.get('selector'))} idx={_sanitize(b.get('idx'))} text={_sanitize(b.get('text'))} nearby_sample={_sanitize(b.get('nearby',''))}")
                struct = b.get('structureSample', [])
                if struct:
                    print('  [STRUCTURE SAMPLE]')
                    for child in struct[:8]:
                        print(f"    - {_sanitize(child.get('tag'))} : {_sanitize(child.get('text'))}")
            caps = data.get('captures', [])
            # Filter out import-only captures (e.g. 'import user/library/version') to avoid noise
            filtered_caps = []
            for c in caps:
                try:
                    if not c:
                        continue
                    s = c.strip()
                    low = s.lower()
                    if re.match(r'^import\b', low) and not ("//@version" in s or "library(" in s or "indicator(" in s or "strategy(" in s or "plot(" in s):
                        # skip import-only capture
                        continue
                    filtered_caps.append(c)
                except Exception:
                    continue
            for i, c in enumerate(filtered_caps):
                s = f"[CAPTURE {i}] {c!r}"
                try:
                    safe = s.encode(sys.stdout.encoding or 'utf-8', errors='backslashreplace').decode(sys.stdout.encoding or 'utf-8', errors='replace')
                    print(safe)
                except Exception:
                    # Fallback: print a backslashescaped representation
                    print(s.encode('utf-8', errors='backslashreplace').decode('ascii', errors='replace'))

            # Also write captures to diagnostics file for inspection
            try:
                diag_dir = self.output_dir
                diag_dir.mkdir(parents=True, exist_ok=True)
                caps_path = diag_dir / 'diagnostic_captures.txt'

                # Normalize, dedupe and keep only captures that look like Pine
                normalized_caps = []
                seen = set()
                for c in filtered_caps:
                    try:
                        if not c:
                            continue
                        nc = self._normalize_source(c)
                        if not ("//@version" in nc or "library(" in nc or "indicator(" in nc or "strategy(" in nc or "plot(" in nc):
                            continue
                        key = nc.strip()[:400]
                        if key in seen:
                            continue
                        seen.add(key)
                        normalized_caps.append(nc)
                    except Exception:
                        continue

                sid = extract_script_id(url) or 'script'
                # If diagnostics are enabled, write diagnostic captures file and a diagnostic .pine/meta
                if not getattr(self, 'suppress_diagnostics', False):
                    try:
                        with open(caps_path, 'w', encoding='utf-8', newline='\n') as cf:
                            for i, c in enumerate(normalized_caps):
                                cf.write(f"[CAPTURE {i}]\n")
                                cf.write(c.rstrip('\n'))
                                cf.write('\n\n' + ('-'*40) + '\n\n')
                        print(f"[DEBUG] Wrote diagnostic captures to: {caps_path}", flush=True)
                    except Exception as e:
                        print(f"[ERROR] Failed to write diagnostic captures: {e}", flush=True)

                # If there is a valid capture, save the first normalized capture as the final .pine (always)
                chosen = normalized_caps[0] if normalized_caps else None
                if chosen:
                    try:
                        out_dir = self.output_dir
                        out_dir.mkdir(parents=True, exist_ok=True)
                        # If diagnostics are enabled, also write the _diagnostic.pine and .meta
                        if not getattr(self, 'suppress_diagnostics', False):
                            fname = f"{sid}_diagnostic.pine"
                            fpath = out_dir / fname
                            with open(fpath, 'w', encoding='utf-8', newline='\n') as wf:
                                wf.write(chosen)
                            meta = {
                                'script_id': sid,
                                'url': url,
                                'captured': True,
                                'downloaded': datetime.now().isoformat()
                            }
                            meta_path = fpath.with_suffix('.meta.json')
                            with open(meta_path, 'w', encoding='utf-8') as mf:
                                json.dump(meta, mf, indent=2, ensure_ascii=False)
                            print(f"[DEBUG] Wrote diagnostic capture to: {fpath}", flush=True)

                        # Always save final via save_script
                        title = await self.page.evaluate("() => { const h = document.querySelector('h1'); return h ? h.textContent.trim() : ''; }")
                        author = await self.page.evaluate("() => { const a = document.querySelector('a[href^=\"/u/\"]'); return a ? a.textContent.trim().replace('by ', '') : ''; }")

                        # Use the exact published date we extracted earlier
                        chosen_lower = (chosen or '').lower()
                        res = {
                            'url': url,
                            'script_id': sid,
                            'title': title or sid,
                            'source_code': chosen,
                            'version': (re.search(r'//@version=(\d+)', chosen) or [None, ''])[1] or '',
                            'author': author or '',
                            'published_date': exact_published_date,  # Use the exact date we extracted
                            'tags': [],
                            'boosts': 0,
                            'source_origin': 'clipboard',
                            'is_library': ('library(' in chosen_lower) or (' library ' in chosen_lower),
                            'is_strategy': 'strategy(' in chosen_lower
                        }
                        saved = self.save_script(res, sid, force_flat=True)
                        print(f"[DEBUG] Also saved via save_script: {saved}", flush=True)
                    except Exception as e:
                        print(f"[ERROR] save_script fallback failed: {e}", flush=True)
                else:
                    # No clipboard capture present; attempt direct page-visible extraction now
                    try:
                        page_visible = await self._try_source_tab_extraction()
                        if page_visible:
                            out_dir = self.output_dir
                            out_dir.mkdir(parents=True, exist_ok=True)
                            vpname = f"{sid}_page_visible.pine"
                            vp_path = out_dir / vpname
                            with open(vp_path, 'w', encoding='utf-8') as vf:
                                vf.write(page_visible)
                            if not getattr(self, 'suppress_diagnostics', False):
                                vp_meta = vp_path.with_suffix('.meta.json')
                                with open(vp_meta, 'w', encoding='utf-8') as vmf:
                                    json.dump({'script_id': sid, 'url': url, 'source': 'page_visible', 'downloaded': datetime.now().isoformat()}, vmf, indent=2, ensure_ascii=False)
                                print(f"[DEBUG] No clipboard capture; wrote page-visible fallback to: {vp_path}", flush=True)
                            # Also attempt to save via save_script for consistent filename/header
                            try:
                                title = await self.page.evaluate("() => { const h = document.querySelector('h1'); return h ? h.textContent.trim() : ''; }")
                                author = await self.page.evaluate("() => { const a = document.querySelector('a[href^=\"/u/\"]'); return a ? a.textContent.trim().replace('by ', '') : ''; }")

                                # Use the exact published date we extracted earlier
                                pv_low = (page_visible or '').lower()
                                res = {
                                    'url': url,
                                    'script_id': sid,
                                    'title': title or sid,
                                    'source_code': page_visible,
                                    'version': (re.search(r'//@version=(\d+)', page_visible) or [None, ''])[1] or '',
                                    'author': author or '',
                                    'published_date': exact_published_date,  # Use the exact date we extracted
                                    'tags': [],
                                    'boosts': 0,
                                    'source_origin': 'page_visible',
                                    'is_library': ('library(' in pv_low) or (' library ' in pv_low),
                                    'is_strategy': 'strategy(' in pv_low
                                }
                                saved = self.save_script(res, sid, force_flat=True)
                                print(f"[DEBUG] Wrote saved script via save_script (page_visible): {saved}", flush=True)
                            except Exception as e:
                                print(f"[ERROR] save_script (page_visible) failed: {e}", flush=True)
                    except Exception as e:
                        print(f"[ERROR] page-visible fallback (no captures case) failed: {e}", flush=True)
            except Exception as e:
                print(f"[ERROR] Failed to write diagnostic captures: {e}", flush=True)

            try:
                cv = await self.page.evaluate('(function(){ try { return window.__cv || {}; } catch(e) { return {}; } })()')
                if not isinstance(cv, dict):
                    cv = dict(cv or {})
                injected_caps = cv.get('captures', [])
                injected_mut = cv.get('mutations', [])
                s1 = f"[INJECTED CAPTURES] {injected_caps[:3]!r}"
                s2 = f"[INJECTED MUTATIONS] {injected_mut[:3]!r}"
                try:
                    print(s1.encode(sys.stdout.encoding or 'utf-8', errors='backslashreplace').decode(sys.stdout.encoding or 'utf-8', errors='replace'))
                except Exception:
                    print(s1.encode('utf-8', errors='backslashreplace').decode('ascii', errors='replace'))
                try:
                    print(s2.encode(sys.stdout.encoding or 'utf-8', errors='backslashreplace').decode(sys.stdout.encoding or 'utf-8', errors='replace'))
                except Exception:
                    print(s2.encode('utf-8', errors='backslashreplace').decode('ascii', errors='replace'))

                # If we captured any clipboard content, offer to save the first valid capture to disk
                try:
                    # Filter injected captures to remove import-only entries
                    caps_to_check = []
                    for c in (injected_caps or []):
                        try:
                            if not c:
                                continue
                            s = c.strip()
                            low = s.lower()
                            if re.match(r'^import\b', low) and not ("//@version" in s or "library(" in s or "indicator(" in s or "strategy(" in s or "plot(" in s):
                                continue
                            caps_to_check.append(c)
                        except Exception:
                            continue

                    chosen = None
                    for c in caps_to_check:
                        if c and ('//@version' in c or 'library(' in c or 'indicator(' in c or 'strategy(' in c):
                            chosen = c
                            break
                    if chosen:
                        out_dir = self.output_dir
                        out_dir.mkdir(parents=True, exist_ok=True)
                        sid = extract_script_id(url) or 'script'

                        # If diagnostics are enabled, write diagnostic files; if suppressed (fast --dump-copy) skip diagnostic sidecars
                        if not getattr(self, 'suppress_diagnostics', False):
                            fname = f"{sid}_diagnostic.pine"
                            fpath = out_dir / fname
                            with open(fpath, 'w', encoding='utf-8') as wf:
                                wf.write(chosen)
                            meta = {
                                'script_id': sid,
                                'url': url,
                                'captured': True,
                                'downloaded': datetime.now().isoformat()
                            }
                            meta_path = fpath.with_suffix('.meta.json')
                            with open(meta_path, 'w', encoding='utf-8') as mf:
                                json.dump(meta, mf, indent=2, ensure_ascii=False)
                            print(f"[DEBUG] Wrote diagnostic capture to: {fpath}", flush=True)

                        # Always save final script via save_script so output matches normal flow
                        try:
                            title = await self.page.evaluate("() => { const h = document.querySelector('h1'); return h ? h.textContent.trim() : ''; }")
                            author = await self.page.evaluate("() => { const a = document.querySelector('a[href^=\"/u/\"]'); return a ? a.textContent.trim().replace('by ', '') : ''; }")

                            # Use the exact published date we extracted earlier
                            res = {
                                'url': url,
                                'script_id': sid,
                                'title': title or sid,
                                'source_code': chosen,
                                'version': (re.search(r'//@version=(\d+)', chosen) or [None, ''])[1] or '',
                                'author': author or '',
                                'published_date': exact_published_date,  # Use the exact date we extracted
                                'tags': [],
                                'boosts': 0,
                                'source_origin': 'clipboard'
                            }
                            saved = self.save_script(res, sid, force_flat=True)
                            print(f"[DEBUG] Wrote saved script via save_script: {saved}", flush=True)
                        except Exception as e:
                            print(f"[ERROR] save_script fallback failed: {e}", flush=True)

                        # If captured content looks truncated, attempt direct page extraction as fallback
                        try:
                            page_visible = await self._try_source_tab_extraction()
                            if page_visible and len(page_visible) > len(chosen):
                                vpname = f"{sid}_page_visible.pine"
                                vp_path = out_dir / vpname
                                with open(vp_path, 'w', encoding='utf-8') as vf:
                                    vf.write(page_visible)
                                if not getattr(self, 'suppress_diagnostics', False):
                                    vp_meta = vp_path.with_suffix('.meta.json')
                                    with open(vp_meta, 'w', encoding='utf-8') as vmf:
                                        json.dump({'script_id': sid, 'url': url, 'source': 'page_visible', 'downloaded': datetime.now().isoformat()}, vmf, indent=2, ensure_ascii=False)
                                    print(f"[DEBUG] Wrote page-visible fallback to: {vp_path}", flush=True)
                        except Exception as e:
                            print(f"[ERROR] page-visible fallback failed: {e}", flush=True)
                except Exception as e:
                    print(f"[ERROR] Failed to write diagnostic capture: {e}", flush=True)

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
        """Scan output dir for existing .pine files and extract their URLs or script IDs.

        Enhanced to detect metadata from `.meta.json` sidecars and from filename patterns
        (script_id as prefix before first underscore), since raw clipboard files may lack
        header comments."""
        found = set()
        try:
            # First scan for .meta.json sidecars (most reliable)
            for meta in self.output_dir.rglob('*.meta.json'):
                try:
                    if any(part.startswith('@') or part in self.ignore_dir_prefixes for part in meta.parts):
                        continue
                    with open(meta, 'r', encoding='utf-8') as mf:
                        try:
                            data = json.load(mf)
                            if data.get('url'):
                                found.add(data['url'])
                            if data.get('script_id'):
                                sid = str(data['script_id']).strip()
                                found.add(sid)
                                try:
                                    found.add(sid.split('-')[0])
                                except Exception:
                                    pass
                        except Exception:
                            continue
                except Exception:
                    continue

            # Fallback: inspect .pine filenames and headers
            for p in self.output_dir.rglob('*.pine'):
                try:
                    if any(part.startswith('@') or part in self.ignore_dir_prefixes for part in p.parts):
                        continue
                    # 1) Try extract script id from filename (format: <script_id>_... .pine)
                    fname = p.name
                    mfn = re.match(r'([A-Za-z0-9]+)_', fname)
                    if mfn:
                        found.add(mfn.group(1))

                    # 2) Try parse header for URL or Script ID (legacy support)
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
                                    except Exception:
                                        pass
                                    break
                    except Exception:
                        pass
                except Exception:
                    continue
        except Exception:
            pass
        return found

    def save_script(self, result: dict, category: str, force_flat: bool = False) -> Path:
        """Save Pine Script to file with metadata."""
        print(f"[DEBUG] save_script called: script_id={result.get('script_id')} title={result.get('title')} category={category} force_flat={force_flat}", flush=True)
        # Bij single script download: force_flat=True, dus direct in output_dir
        try:
            if force_flat:
                out_dir = self.output_dir
            else:
                out_dir = self.output_dir / sanitize_filename(category)
                out_dir.mkdir(parents=True, exist_ok=True)
            safe_title = sanitize_filename(result.get('title') or 'unknown')
            filename = f"{result.get('script_id')}_{safe_title}.pine"
            filepath = out_dir / filename
            tags_str = ', '.join(result.get('tags', [])) if result.get('tags') else ''
            # Determine Type label using flags and available source text (source_code or source_raw) to handle raw clipboard cases
            combined_source = (result.get('source_code') or '') + '\n' + (result.get('source_raw') or '')
            src_lower = combined_source.lower()
            if result.get('is_library') or 'library(' in src_lower or '@library' in src_lower:
                type_label = 'Library'
            elif result.get('is_strategy') or 'strategy(' in src_lower:
                type_label = 'Strategy'
            else:
                type_label = 'Indicator'

            header = [
                f"// Title: {result.get('title')}",
                f"// Script ID: {result.get('script_id')}",
                f"// Author: {result.get('author')}",
                f"// URL: {result.get('url')}",
                f"// Published: {result.get('published_date','')}",
                f"// Downloaded: {datetime.now().isoformat()}",
                f"// Pine Version: {result.get('version','')}",
                f"// Type: {type_label}",
                f"// Boosts: {result.get('boosts',0)}",
                f"// Tags: {tags_str}",
                "//",
                ""
            ]
            if result.get('source_origin') == 'clipboard' and result.get('source_raw'):
                raw = result.get('source_raw')
                if not isinstance(raw, str):
                    raw = str(raw)
                # Normalize newlines and unicode escapes
                try:
                    raw = self._normalize_source(raw)
                except Exception:
                    pass
                # Write header + raw payload as text with explicit LF newlines to prevent doubled blank lines on Windows
                with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
                    f.write('\n'.join(header))
                    f.write(raw)
                print(f"[DEBUG] Saved raw clipboard script (with header) to {filepath}")
                return filepath
            source = result.get('source_code') or ''
            if isinstance(source, str):
                try:
                    if '\\n' in source or '\\t' in source or '\\u' in source:
                        try:
                            source = codecs.decode(source, 'unicode_escape')
                        except Exception as e:
                            print(f"[ERROR] unicode_escape decode: {e}")
                            source = source.replace('\\n','\n').replace('\\r','\r').replace('\\t','\t')
                            source = source.replace('\\"','"').replace(r'\/','/')
                    source = source.strip('\n')
                except Exception as e:
                    print(f"[ERROR] source string handling: {e}")
            else:
                source = str(source)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(header))
                f.write(source)
                f.write('\n')
            # Create/update a simple marker file so it's easy to find where things were written
            try:
                marker = out_dir / '.last_saved.txt'
                with open(marker, 'w', encoding='utf-8') as mf:
                    mf.write(str(filepath))
                print(f"[DEBUG] Writing script to: {filepath}")
                print(f"[DEBUG] Marker written to: {marker}", flush=True)
            except Exception as e:
                print(f"[ERROR] Failed to write marker: {e}", flush=True)
            return filepath
        except Exception as e:
            print(f"[ERROR] Exception in save_script: {e}")
            raise

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
        print(f"\nMetadata exported: {metadata_path}")

    async def download_all(self, base_url: str, max_pages: int = 30, delay: float = 2.0, resume: bool = True, debug_pages: bool = False):
        """Download all scripts from a listing page (or generated template pages).

        This enforces copy-button-only extraction per script, with retries and verification.
        Parameters:
          - base_url: listing page URL
          - max_pages: max number of generated/listing pages to visit
          - delay: seconds to wait between scripts
          - resume: skip already-downloaded scripts
          - debug_pages: enable verbose page debug logging
        """
        parsed = urlparse(base_url)
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]
        category = path_parts[-1] if path_parts else "scripts"

        print(f"\n{'='*70}")
        print(f"  TradingView Pine Script Downloader (Enhanced - batch)")
        print(f"{'='*70}")
        print(f"  URL: {base_url}")
        print(f"  Category: {category}")
        print(f"  Output: {self.output_dir}")
        print(f"{'='*70}\n")

        await self.setup()

        try:
            # Navigate to base listing page first (ensure content is loaded)
            try:
                await self.page.goto(base_url, wait_until='networkidle', timeout=60000)
                await self.page.wait_for_timeout(1200)
            except Exception:
                pass

            # Collect scripts from listing
            scripts = await self.get_scripts_from_listing(max_scroll_attempts=max_pages, debug_pages=debug_pages)
            if not scripts:
                print("ERROR: No scripts found on listing page!")
                return

            # Resume: skip scripts we already have
            completed = set()
            if resume:
                completed = self._scan_existing_scripts()
                if completed:
                    print(f"Resuming: found {len(completed)} existing scripts to skip")

            # Filter scripts and prepare worklist
            worklist = [s for s in scripts if s['url'] not in completed]
            if not worklist:
                print("No new scripts to download.")
                return

            print(f"\n{'='*70}")
            print(f"  Downloading {len(worklist)} scripts...")
            print(f"{'='*70}\n")

            for i, script_info in enumerate(worklist, 1):
                url = script_info['url']
                title = (script_info.get('title') or 'Unknown')[:50]
                print(f"[{i}/{len(worklist)}] {title} - {url}")

                # Create an isolated context+page for this script so batch behavior matches single-script runs
                old_context = self.context
                old_page = self.page
                script_context = None
                try:
                    # Zet viewport terug naar 1280x720 (standaard) in batch mode
                    script_context = await self.browser.new_context(
                        viewport={'width': 1280, 'height': 720},
                        user_agent=self.current_user_agent,
                        locale='en-US',
                        timezone_id='America/New_York',
                        java_script_enabled=True,
                        has_touch=False,
                        is_mobile=False,
                        permissions=["clipboard-read", "clipboard-write"],
                    )
                    script_page = await script_context.new_page()

                    # Mirror per-page init: mask webdriver and attach handlers BEFORE navigation
                    try:
                        await script_page.add_init_script("""
                            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
                            window.chrome = {runtime:{}};
                        """)
                    except Exception:
                        pass

                    try:
                        script_page.on('dialog', lambda dialog: dialog.accept())
                        script_page.on('crash', lambda *args: print('[page] Page crash event detected'))
                        script_page.on('close', lambda *args: print('[page] Page close event detected'))
                    except Exception:
                        pass

                    # Inject copy-capture and debug hooks before navigation (ensures early captures)
                    try:
                        await script_page.add_init_script(r'''() => {
                            window.__cv = window.__cv || { captures: [], mutations: [], logs: [] };
                            document.addEventListener('copy', function(e){ try { const t = (e.clipboardData && e.clipboardData.getData('text/plain')) || document.getSelection().toString(); if (t) window.__cv.captures.push(t); window.__cv.logs.push({type:'copy-event', text:t, time:Date.now()}); } catch(e){} }, true);
                            try{ const origWrite = navigator.clipboard && navigator.clipboard.writeText; if (origWrite) { navigator.clipboard.writeText = async function(t){ try{ window.__cv.captures.push(t || ''); window.__cv.logs.push({type:'clipboard.writeText', text:t, time:Date.now()}); }catch(e){}; return origWrite.call(this, t); }; } }catch(e){}
                            try{ const origExec = Document.prototype.execCommand; Document.prototype.execCommand = function(cmd){ if (cmd === 'copy') { try{ window.__cv.captures.push(document.getSelection().toString()); window.__cv.logs.push({type:'execCommand', selection:document.getSelection().toString(), time:Date.now()}); }catch(e){} } return origExec.apply(this, arguments); }; }catch(e){}
                        }''')
                    except Exception:
                        pass

                    # Switch current context/page to the new ones for the extract flow
                    self.context = script_context
                    self.page = script_page
                except Exception as e:
                    # Fallback to using the existing page if creating a fresh context fails
                    print(f"   [debug] Failed to create isolated context/page: {e} - using existing page")
                    script_context = None
                    self.context = old_context
                    self.page = old_page

                # Track success state and ensure we close the script context afterwards
                script_context_created = bool(script_context)


                max_attempts = 1 if getattr(self, 'fast_mode', False) else 3
                effective_delay = 0.5 if getattr(self, 'fast_mode', False) else delay
                succeeded = False
                try:
                    for attempt in range(1, max_attempts + 1):
                        try:
                            # Ensure overlays cleared before each attempt
                            try:
                                await self.handle_overlays()
                            except Exception:
                                pass

                            # Extract using strict clipboard/copy-button flow
                            # Diagnostic: if positional click is enabled, log scroll position before attempting
                            if getattr(self, 'positional_click', False) and getattr(self, 'debug_pages', False):
                                try:
                                    pre_scroll = await self.page.evaluate('() => ({x: window.scrollX, y: window.scrollY})')
                                    print(f"   [debug] Pre-extract scroll: {pre_scroll}")
                                except Exception:
                                    pass

                            res = await self.extract_pine_source(url, isolated=script_context_created)

                            # After extraction, save a post-extract screenshot for debugging positional failures
                            if getattr(self, 'positional_click', False):
                                try:
                                    dbg_dir = self.output_dir / 'debug_positional'
                                    dbg_dir.mkdir(parents=True, exist_ok=True)
                                    ss_after = dbg_dir / f"{res.get('script_id')}_after_extract.png"
                                    await self.page.screenshot(path=str(ss_after))
                                    if getattr(self, 'debug_pages', False):
                                        print(f"   [debug] Saved positional post-extract screenshot: {ss_after}")
                                except Exception:
                                    pass

                            # Diagnostic: log post-extract scroll position
                            if getattr(self, 'positional_click', False) and getattr(self, 'debug_pages', False):
                                try:
                                    post_scroll = await self.page.evaluate('() => ({x: window.scrollX, y: window.scrollY})')
                                    print(f"   [debug] Post-extract scroll: {post_scroll}")
                                except Exception:
                                    pass

                            res['attempt'] = attempt
                            self.results.append(res)

                            if res.get('source_origin') == 'clipboard' and res.get('source_raw'):
                                fp = self.save_script(res, category, force_flat=True)
                                print(f"         OK: Saved: {fp.name[:60]}")
                                self.stats['downloaded'] += 1
                                succeeded = True
                                break

                            # Skip protected or invite-only
                            if res.get('error') in ['invite-only', 'protected', 'not open-source']:
                                print(f"         SKIPPED: {res.get('error')}")
                                self.stats['skipped_protected'] += 1
                                succeeded = True
                                break

                            # No source found
                            if res.get('error') == 'clipboard_extraction_failed' or res.get('error') == 'stale_clipboard' or not res.get('source_code'):
                                print(f"         ERROR: Attempt {attempt} failed: {res.get('error')}")
                                # Recovery actions: prefer a soft context restart on attempt 2 to keep browser process
                                if attempt == 2:
                                    print("         [recovery] soft-restarting browser context and retrying...")
                                    try:
                                        await self._restart_context()
                                    except Exception as e:
                                        print(f"         [recovery] soft restart failed: {e} - falling back to full restart")
                                        try:
                                            await self.cleanup()
                                        except Exception:
                                            pass
                                        await self.setup()
                                await self.page.wait_for_timeout(300 if getattr(self, 'fast_mode', False) else 800)
                                continue
                        except TargetClosedError as e:
                            print(f"         ERROR: Attempt {attempt} TargetClosedError: {e} - restarting browser context and retrying")
                            try:
                                await self.cleanup()
                            except Exception:
                                pass
                            try:
                                await self.setup()
                            except Exception as e2:
                                print(f"         ERROR: Restart failed: {e2}")
                                # If restart fails, give up on this attempt
                                continue
                            # short wait and then retry attempt (will increment)
                            await self.page.wait_for_timeout(500)
                            continue
                        except Exception as e:
                            print(f"         ERROR: Attempt {attempt} exception: {e}")
                            if attempt == 2:
                                try:
                                    await self.cleanup()
                                except Exception:
                                    pass
                                await self.setup()
                            continue
                finally:
                    # Ensure we close the temporary context/page and restore the original
                    try:
                        if script_context_created and self.context:
                            try:
                                await self.context.close()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    finally:
                        # restore listing context/page
                        self.context = old_context
                        self.page = old_page
                    
                    # If page/context unexpectedly closed earlier, don't crash entire batch; continue to next
                    try:
                        if not succeeded:
                            # record failure if not already recorded
                            pass
                    except Exception:
                        pass

                if not succeeded:
                    print(f"         ERROR: Failed after {max_attempts} attempts: {url}")
                    self.stats['failed'] += 1

                # Wait between scripts (guard if page/context was closed unexpectedly)
                if i < len(worklist):
                    try:
                        await self.page.wait_for_timeout(int(delay * 1000))
                    except TargetClosedError:
                        print('   [debug] Page closed during inter-script wait; restarting browser and continuing')
                        try:
                            await self.cleanup()
                        except Exception:
                            pass
                        try:
                            await self.setup()
                        except Exception:
                            pass
                        # continue to next script without failing the whole batch
                        continue

            # Export metadata and print summary
            self._export_metadata(category)
            self._print_summary(category)

        finally:
            await self.cleanup()

    async def _restart_context(self):
        """Soft restart: close and recreate the browser context and page without closing the browser process.

        This keeps browser binaries and permissions intact and is much faster than a full browser restart.
        """
        try:
            if getattr(self, 'debug_pages', False):
                print('   [debug] Performing soft context restart...')
            try:
                if self.context:
                    await self.context.close()
            except Exception:
                pass

            # FIX: Use consistent 1280x720 viewport on context restart to ensure copy UI stays visible
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent=self.current_user_agent,
                locale='en-US',
                timezone_id='America/New_York',
                java_script_enabled=True,
                has_touch=False,
                is_mobile=False,
                permissions=["clipboard-read", "clipboard-write"],
            )
            self.page = await self.context.new_page()
            try:
                await self.page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                """)
            except Exception:
                pass
            await self.page.goto('about:blank')
            await self.page.wait_for_timeout(200)
        except Exception as e:
            raise e


    def _print_summary(self, category: str):
        """Print final summary."""
        print(f"\n{'='*70}")
        print(f"  SUMMARY")
        print(f"{'='*70}")
        print(f"  Downloaded:          {self.stats['downloaded']}")
        print(f"  Protected/Private:   {self.stats['skipped_protected']}")
        print(f"  No Source Found:     {self.stats['skipped_no_code']}")
        print(f"  Failed:              {self.stats['failed']}")
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
    parser.add_argument('--dump-copy', action='store_true', help='Fast mode: use dump-copy style capture (fast) but do not write diagnostic files')
    parser.add_argument('--dump-copy-diagnostics', action='store_true', help='Fast diagnostic flow (dump-copy style). Does NOT write diagnostic files unless --write-diagnostics is provided')
    parser.add_argument('--write-diagnostics', action='store_true', help='When used with --dump-copy-diagnostics write diagnostic captures and files to the output dir')
    parser.add_argument('--positional-click', action='store_true', help='Use fixed-position click to trigger copy button (fast, fragile)')
    parser.add_argument('--status', action='store_true', help='Show status of output directory (progress files, existing .pine files) and exit')

    args = parser.parse_args()

    # Require --url unless --status is used (so --status can run standalone)
    if not args.url and not args.status:
        parser.error('the following arguments are required: --url (unless --status is provided or DOWNLOAD_URL env var is set)')
    
    scraper = EnhancedTVScraper(
        output_dir=args.output,
        headless=not args.visible
    )

    # Apply optional flags
    scraper.positional_click = args.positional_click
    scraper.debug_pages = args.debug_pages


    if args.status:
        scraper.print_status()
        return

    if args.dump_copy_diagnostics:
        if not args.url or '/script/' not in args.url:
            parser.error('--dump-copy-diagnostics requires a single script URL (contains "/script/")')
        # Run the fast dump-copy diagnostic flow but by default do NOT write diagnostic files unless --write-diagnostics is provided
        scraper.dump_copy_mode = True
        scraper.suppress_diagnostics = not args.write_diagnostics
        if scraper.suppress_diagnostics:
            try:
                scraper._clean_diagnostic_files()
            except Exception:
                pass
        await scraper.dump_copy_diagnostics(args.url)
        return

    if args.dump_copy:
        # Enable fast dump-copy mode (do not write diagnostic capture files by default)
        scraper.dump_copy_mode = True
        scraper.suppress_diagnostics = True

    # If a single script URL was provided, run the simple single-script flow instead of download_all
    if args.url and '/script/' in args.url:
        scraper.debug_pages = args.debug_pages
        # If running in fast dump-copy mode, remove prior diagnostic artifacts to keep output clean
        if getattr(scraper, 'suppress_diagnostics', False):
            try:
                scraper._clean_diagnostic_files()
            except Exception:
                pass
        await scraper.setup()
        try:
            print('Processing single script URL...')
            res = await scraper.extract_pine_source(args.url)
            print(f"[DEBUG] extract_pine_source returned: script_id={res.get('script_id')} title={res.get('title')} source_len={len(res.get('source_code') or '')} error={res.get('error')}", flush=True)

            if not getattr(scraper, 'suppress_diagnostics', False):
                # Always write a diagnostic JSON to the requested output dir so we can inspect results
                try:
                    out_dir = Path(args.output)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    diag_path = out_dir / 'last_result.json'
                    with open(diag_path, 'w', encoding='utf-8') as df:
                        json.dump(res, df, indent=2, ensure_ascii=False)
                    print(f"[DEBUG] Wrote diagnostic JSON to: {diag_path}", flush=True)
                    # If clipboard/raw payload exists, write it as a raw .pine so you can inspect it
                    if res.get('source_raw'):
                        raw_path = out_dir / f"{res.get('script_id')}_raw.pine"
                        with open(raw_path, 'w', encoding='utf-8') as rf:
                            rf.write(res.get('source_raw'))
                        print(f"[DEBUG] Wrote raw clipboard to: {raw_path}", flush=True)
                except Exception as e:
                    print(f"[ERROR] Failed to write diagnostic files: {e}", flush=True)

            # Prefer saving captured clipboard payloads even when extract reported a non-fatal error
            if res.get('source_origin') == 'clipboard' and res.get('source_raw') and ("//@version" in res.get('source_raw') or "library(" in res.get('source_raw') or "indicator(" in res.get('source_raw') or "plot(" in res.get('source_raw')):
                category = extract_script_id(args.url) or 'scripts'
                print(f"[DEBUG] about to call save_script: category={category} output_dir={scraper.output_dir}", flush=True)
                fp = scraper.save_script(res, category, force_flat=True)
                print(f"[DEBUG] save_script returned: {fp}", flush=True)
                try:
                    written_bytes = Path(fp).read_bytes()
                    raw_bytes = res.get('source_raw').encode('utf-8')
                    if written_bytes != raw_bytes:
                        print('Warning: written file does not match raw clipboard payload. Preserving header and writing raw payload after header...')
                        try:
                            # Preserve leading comment header lines (// ...) and prepend before raw payload
                            txt = Path(fp).read_text(encoding='utf-8', errors='replace')
                            lines = txt.splitlines()
                            header_end = 0
                            for i, ln in enumerate(lines[:40]):
                                if not ln.strip().startswith('//') and ln.strip() != '':
                                    header_end = i
                                    break
                                header_end = i + 1
                            header_text = ('\n'.join(lines[:header_end]) + '\n') if header_end else ''
                            new_bytes = header_text.encode('utf-8') + raw_bytes.lstrip(b'\n')
                            Path(fp).write_bytes(new_bytes)
                        except Exception:
                            # Fallback to raw bytes if anything fails
                            Path(fp).write_bytes(raw_bytes)
                    else:
                        print('Verified: saved file matches clipboard content (byte-for-byte)')
                except Exception:
                    pass
            elif res.get('source_code'):
                # Use script id as category for single downloads
                category = extract_script_id(args.url) or 'scripts'
                print(f"[DEBUG] about to call save_script: category={category} output_dir={scraper.output_dir}", flush=True)
                fp = scraper.save_script(res, category, force_flat=True)
                print(f"[DEBUG] save_script returned: {fp}", flush=True)
            elif res.get('error'):
                print(f"Error: {res.get('error')}")
            elif res.get('source_code'):
                # Use script id as category for single downloads
                category = extract_script_id(args.url) or 'scripts'
                print(f"[DEBUG] about to call save_script: category={category} output_dir={scraper.output_dir}", flush=True)
                fp = scraper.save_script(res, category, force_flat=True)
                print(f"[DEBUG] save_script returned: {fp}", flush=True)
                try:
                    written_bytes = Path(fp).read_bytes()
                    if res.get('source_origin') == 'clipboard' and res.get('source_raw'):
                        raw_bytes = res.get('source_raw').encode('utf-8')
                        if written_bytes != raw_bytes:
                            print('Warning: written file does not match raw clipboard payload. Preserving header and writing raw payload after header...')
                            try:
                                txt = Path(fp).read_text(encoding='utf-8', errors='replace')
                                lines = txt.splitlines()
                                header_end = 0
                                for i, ln in enumerate(lines[:40]):
                                    if not ln.strip().startswith('//') and ln.strip() != '':
                                        header_end = i
                                        break
                                    header_end = i + 1
                                header_text = ('\n'.join(lines[:header_end]) + '\n') if header_end else ''
                                new_bytes = header_text.encode('utf-8') + raw_bytes.lstrip(b'\n')
                                Path(fp).write_bytes(new_bytes)
                            except Exception:
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

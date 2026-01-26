"""Quick script to verify Playwright browsers work inside the container."""
import asyncio
import sys
from playwright.async_api import async_playwright

async def check():
    try:
        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('https://example.com', wait_until='domcontentloaded', timeout=15000)
        title = await page.title()
        print(f"Success: opened Chromium and accessed example.com (title: {title})")
        await browser.close()
        await p.stop()
        return 0
    except Exception as e:
        print(f"ERROR: Playwright check failed: {e}")
        return 2

if __name__ == '__main__':
    sys.exit(asyncio.run(check()))

# TradingView Pine Script Downloader

## Project Summary
Automated tool to download open-source Pine Script indicators/strategies from TradingView using Playwright browser automation.

## File Overview

| File | Purpose | Recommended |
|------|---------|-------------|
| `tv_downloader_enhanced.py` | Full-featured with progress resume, multiple extraction strategies | ✅ Production |
| `tv_downloader_fixed.py` | Clean implementation with fixed open-source detection | ✅ Simple use |
| `tv_pinescript_downloader.py` | Original base implementation | ❌ Has bugs |
| `batch_download.py` | Process multiple URLs from file or CLI | ✅ Batch jobs |

## Key Technical Details

### Open-Source Detection (CRITICAL)
TradingView renders a text label for open-source scripts. **Do NOT use lock icon detection** - it causes false positives.

```javascript
// CORRECT - Check for explicit text
const pageUpper = document.body.innerText.toUpperCase();
const isOpenSource = pageUpper.includes('OPEN-SOURCE SCRIPT');

// Also check for protected/invite-only (these override open-source)
const isProtected = pageText.toLowerCase().includes('protected script');
const isInviteOnly = pageText.toLowerCase().includes('invite-only');
```

### Source Code Extraction (CRITICAL)
TradingView renders code as **individual div elements** (one per line), NOT in `<pre>` tags.

```javascript
// Strategy 1: Find container with 50+ child divs
for (const container of allDivs) {
    const children = Array.from(container.children);
    if (children.length > 50) {
        const texts = children.map(c => c.textContent?.trim() || '');
        // Filter out line numbers (pure numeric strings)
        const codeLines = texts.filter(t => t && !/^\d+$/.test(t));
        return codeLines.join('\n');
    }
}

// Strategy 2: Fallback to <pre> and <code> elements
const codeElements = document.querySelectorAll('pre code, pre');

// Strategy 3 (Enhanced only): Look for embedded JSON script data
```

### Playwright Configuration
```python
# Browser args to avoid detection
args=[
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-dev-shm-usage'
]

# Context settings
viewport={'width': 1920, 'height': 1080}
user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...'
locale='en-US'
```

### Timing/Delays
- 2.0 seconds default between script downloads
- 2-3 seconds after page navigation
- 1.5-2.5 seconds after "Show more" clicks
- Page timeout: 30-60 seconds

## Common Patterns

### Script URL Extraction
```python
# Extract script ID from URL like /script/ABC123-Name
def extract_script_id(url: str) -> str:
    match = re.search(r'/script/([^/]+)', url)
    return match.group(1).split('-')[0] if match else ''
```

### Pagination Handling
- TradingView uses "Show more" buttons for infinite scroll
- Click button repeatedly, track URLs in dict to deduplicate
- Stop when no new scripts found for N attempts

### Progress Persistence (Enhanced version)
- `.progress.json` tracks completed script URLs
- Saves after every 10 scripts
- Resume by checking URLs on restart

## Output Structure
```
pinescript_downloads/
└── {category}/
    ├── {script_id}_{script_name}.pine
    ├── metadata.json
    └── .progress.json
```

## Known Issues & TODOs

### Issues
- Generic `except: pass` blocks hide errors
- No logging framework (prints only)
- Fixed timeouts (should be configurable)
- No retry logic for transient failures

### Potential Improvements
- [ ] Add proper logging instead of print statements
- [ ] Implement retry logic for timeouts/network errors
- [ ] Extract common code into shared module (reduce duplication)
- [ ] Add unit tests for extraction logic
- [ ] Concurrent downloads (multiple browser contexts)
- [ ] Adaptive rate limiting based on response times

## Quick Commands

```bash
# Install
pip install -r requirements.txt
playwright install chromium

# Download from a page
python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/"

# Resume interrupted download (automatic)
python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/"

# Start fresh
python tv_downloader_enhanced.py --url "..." --no-resume

# Debug with visible browser
python tv_downloader_enhanced.py --url "..." --visible

# Batch from file
python batch_download.py example_urls.txt
```

# TradingView Pine Script Downloader - Complete Documentation

## Overview

This is an advanced web scraper designed to download Pine Script source code from TradingView. It uses Playwright for browser automation and implements sophisticated extraction techniques to handle TradingView's dynamic interface.

**Version**: Enhanced (with multiple extraction strategies)  
**Primary Method**: Clipboard/copy-button extraction  
**Language**: Python 3  
**Key Dependency**: Playwright (async)

---

## Table of Contents

1. [Features](#features)
2. [Installation](#installation)
3. [Usage](#usage)
4. [Architecture](#architecture)
5. [Command-Line Options](#command-line-options)
6. [Environment Variables](#environment-variables)
7. [Extraction Methods](#extraction-methods)
8. [File Organization](#file-organization)
9. [Troubleshooting](#troubleshooting)
10. [Known Issues & Fixes](#known-issues--fixes)

---

## Features

### Core Capabilities

- **Multiple Extraction Strategies**: Clipboard capture, positional clicking, DOM extraction
- **Anti-Detection**: User agent rotation, human-like behavior simulation, overlay handling
- **Resume Support**: Skip already-downloaded scripts
- **Batch Processing**: Download entire script collections with pagination support
- **Metadata Extraction**: Captures title, author, tags, boosts, publication date
- **Protected Script Detection**: Identifies invite-only and protected scripts
- **Progress Tracking**: JSON-based progress files for resuming interrupted downloads
- **Diagnostic Mode**: Debug copy-button interactions and clipboard captures

### Advanced Features

- **Stale Clipboard Detection**: SHA-256 hashing to prevent duplicate clipboard reuse
- **Context Isolation**: Each script downloads in isolated browser context (batch mode)
- **Automatic Recovery**: Context restart on failures, overlay removal, cookie consent handling
- **Fast Mode**: Reduced delays and retries for quicker processing (`--dump-copy`)
- **Positional Click**: Fixed-coordinate clicking for stable layouts (`--positional-click`)

---

## Installation

### Prerequisites

```bash
# Python 3.8 or higher required
python --version

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
python -m playwright install
```

### Optional: Container / Docker (note)

This repository does **not** include Docker images or Docker-specific files. If you want to run the downloader inside a container, create a minimal Dockerfile that installs Python, the project dependencies and Playwright browsers. Example steps to run inside a container or VM:

```bash
# inside the container or VM
pip install -r requirements.txt
python -m playwright install
```

### Verify Installation

```bash
python tv_downloader_enhanced.py --help
```

---

## Usage

### Single Script Download

```bash
# Basic single script download
python tv_downloader_enhanced.py --url "https://www.tradingview.com/script/ABC123-script-name/"

# With visible browser (for debugging)
python tv_downloader_enhanced.py --url "https://..." --visible

# Using positional click (faster, fragile)
python tv_downloader_enhanced.py --url "https://..." --positional-click

# Fast mode (no diagnostics)
python tv_downloader_enhanced.py --url "https://..." --dump-copy
```

### Batch Download (Collection/Listing)

```bash
# Download all scripts from a listing page
python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/..."

# With custom settings
python tv_downloader_enhanced.py \
  --url "https://www.tradingview.com/scripts/most-popular/" \
  --output ./my_scripts \
  --delay 3.0 \
  --max-pages 50 \
  --visible

# Resume interrupted download
python tv_downloader_enhanced.py --url "https://..." 
# (resume is enabled by default; use --no-resume to start fresh)
```

### Diagnostic Modes

```bash
# Dump copy diagnostics (inspect clipboard captures)
python tv_downloader_enhanced.py \
  --url "https://www.tradingview.com/script/ABC123-..." \
  --dump-copy-diagnostics

# Write diagnostic files to disk
python tv_downloader_enhanced.py \
  --url "https://..." \
  --dump-copy-diagnostics \
  --write-diagnostics

# Enable verbose page logging
python tv_downloader_enhanced.py --url "https://..." --debug-pages
```

### Status Check

```bash
# Show progress and existing files
python tv_downloader_enhanced.py --status
```

---

## Architecture

### Class Structure

```
EnhancedTVScraper
├── Browser Management
│   ├── setup()                    # Initialize browser/context
│   ├── cleanup()                  # Close browser safely
│   └── _restart_context()         # Soft context restart
│
├── Extraction Methods
│   ├── extract_pine_source()      # Main extraction orchestrator
│   ├── _try_copy_button_extraction()
│   ├── _try_positional_click_extraction()
│   ├── _try_source_tab_extraction()
│   ├── _try_direct_extraction()
│   └── _try_embedded_extraction()
│
├── Page Handling
│   ├── handle_cookie_consent()
│   ├── handle_overlays()
│   ├── _human_like_delay()
│   ├── _human_like_scroll()
│   └── _human_like_mouse_move()
│
├── Batch Processing
│   ├── download_all()
│   ├── get_scripts_from_listing()
│   ├── load_progress()
│   └── save_progress()
│
├── File Management
│   ├── save_script()              # Save .pine file with metadata
│   ├── _scan_existing_scripts()   # Find downloaded scripts
│   ├── _export_metadata()         # Export metadata.json
│   └── _normalize_source()        # Normalize encoding/whitespace
│
└── Diagnostics
    ├── dump_copy_diagnostics()    # Diagnostic report
    └── _clean_diagnostic_files()
```

### Data Flow

```
1. Navigate to script URL
2. Wait for page load + handle overlays
3. Click "Source code" tab (if present)
4. Attempt clipboard extraction:
   a. Try positional click (if enabled)
   b. Try copy button selectors
   c. Read clipboard/in-page captures
5. Verify clipboard content (hash check, snippet match)
6. Normalize source code (unicode escapes, newlines)
7. Save to .pine file with header metadata
8. Update progress tracking
```

---

## Command-Line Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--url` | `-u` | `$DOWNLOAD_URL` | TradingView script/listing URL |
| `--output` | `-o` | Auto-detected* | Output directory |
| `--delay` | `-d` | `2.0` | Seconds between requests |
| `--max-pages` | `-p` | `20` | Max listing pages to scan |
| `--visible` | | `False` | Show browser window (headless=False) |
| `--no-resume` | | `False` | Ignore progress, start fresh |
| `--debug-pages` | | `False` | Verbose page visit logging |
| `--dump-copy` | | `False` | Fast mode (no diagnostic files) |
| `--dump-copy-diagnostics` | | `False` | Run diagnostic flow |
| `--write-diagnostics` | | `False` | Write diagnostic files (with `--dump-copy-diagnostics`) |
| `--positional-click` | | `False` | Use fixed-position click |
| `--status` | | `False` | Show status and exit |

\* **Output auto-detection**: `$PINE_OUTPUT_DIR` → `/mnt/pinescripts` (if exists) → `./pinescript_downloads`

---

## Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `DOWNLOAD_URL` | Default URL for `--url` | `https://www.tradingview.com/script/...` |
| `PINE_OUTPUT_DIR` | Default output directory | `/home/user/scripts` |
| `PINE_IGNORE_DIRS` | Comma-separated dirs to ignore | `@Recycle,@Recently-Snapshot` |

### Example `.env` setup:

```bash
export PINE_OUTPUT_DIR="/mnt/pinescripts"
export DOWNLOAD_URL="https://www.tradingview.com/scripts/most-popular/"
export PINE_IGNORE_DIRS="@Recycle,@tmp"

python tv_downloader_enhanced.py
```

---

## Extraction Methods

### 1. Copy Button Extraction (Primary)

**Strategy**: Locate and click copy buttons, read clipboard

```python
# Selectors tried (in order):
- button[aria-label*="copy"]
- button[title*="Copy"]
- .copy-to-clipboard
- [data-qa-id*="copy"]
- button:has-text("Copy")
```

**Verification**:
- SHA-256 hash deduplication (prevents stale clipboard reuse)
- Snippet matching against visible page source
- Pine Script signature check (`//@version`, `indicator(`, `library(`)

### 2. Positional Click Extraction

**Strategy**: Click fixed coordinates inside code container (fast but fragile)

**When to use**: `--positional-click` flag for stable layouts

**Coordinates**:
```python
# Finds code container bounding box
# Clicks: x = (width - 40), y = 30
# Targets top-right copy button region
```

**Trade-offs**:
- ✅ 3-5x faster than selector-based extraction
- ❌ Breaks if layout changes or viewport differs
- ❌ May click wrong element if overlays present

### 3. Source Tab Extraction (Fallback)

**Strategy**: Extract visible text from DOM after clicking "Source code" tab

```javascript
// Looks for containers with many child divs (line-by-line code)
// Joins text content from child elements
// Filters out line numbers (e.g., /^\d+$/)
```

### 4. Direct/Embedded Extraction (Legacy)

**Strategy**: Extract from page scripts or embedded JSON data

- Searches `<script>` tags for JSON with `"source": "..."`
- Decodes escaped strings (`\n`, `\t`, `\"`)
- Rarely works on modern TradingView pages

---

## File Organization

### Output Structure

```
pinescript_downloads/
├── script_category/               # Batch downloads organized by category
│   ├── ABC123_Script_Name.pine
│   ├── DEF456_Another_Script.pine
│   ├── metadata.json              # Batch metadata export
│   └── .progress.json             # Resume tracking
│
├── XYZ789_Single_Script.pine      # Single downloads (flat)
├── XYZ789_Single_Script.meta.json # Metadata sidecar
│
├── diagnostic_captures.txt        # Debug mode outputs
├── last_result.json
└── debug_positional/              # Positional click screenshots
    ├── ABC123_before_pos_click.png
    └── ABC123_after_extract.png
```

### File Format: .pine

```pine
// Title: Example Script Name
// Script ID: ABC123xyz
// Author: username
// URL: https://www.tradingview.com/script/ABC123xyz-example-script/
// Published: 2024-01-15T10:30:00Z
// Downloaded: 2026-02-02T14:22:10.123456
// Pine Version: 5
// Type: Indicator
// Boosts: 836
// Tags: momentum, RSI, custom indicators
//

//@version=5
indicator("Example Script", overlay=true)
// ... source code ...
```

### Metadata Sidecar: .meta.json

```json
{
  "script_id": "ABC123xyz",
  "url": "https://www.tradingview.com/script/ABC123xyz-example-script/",
  "captured": true,
  "downloaded": "2026-02-02T14:22:10.123456",
  "source": "clipboard"
}
```

---

## Troubleshooting

### Common Issues

#### 1. **Clipboard Extraction Failed**

**Symptoms**: `ERROR: clipboard_extraction_failed` or empty source code

**Causes**:
- Clipboard permissions denied
- Copy button not clicked properly
- Overlays blocking interaction
- Stale clipboard content

**Solutions**:
```bash
# Try visible mode to see what's happening
python tv_downloader_enhanced.py --url "..." --visible

# Use diagnostic mode
python tv_downloader_enhanced.py --url "..." --dump-copy-diagnostics

# Try positional click (if layout is stable)
python tv_downloader_enhanced.py --url "..." --positional-click
```

#### 2. **TargetClosedError / Page Crashes**

**Symptoms**: `TargetClosedError`, browser context closes unexpectedly

**Causes**:
- Site-triggered navigation
- Memory pressure
- Anti-bot detection

**Solutions**:
```bash
# The script auto-restarts context on errors
# For persistent issues, increase delay:
python tv_downloader_enhanced.py --url "..." --delay 5.0

# Or use single-script mode (more stable):
python tv_downloader_enhanced.py --url "https://www.tradingview.com/script/ABC123-..."
```

#### 3. **Stale Clipboard Detected**

**Symptoms**: `ERROR: stale_clipboard`, same source code for different scripts

**Causes**:
- Clipboard not cleared between scripts
- Browser reusing cached copy data

**Solutions**:
```bash
# Script automatically retries with clipboard clearing
# If persistent, restart browser context manually (automatic on attempt 3)

# Or use fast mode which suppresses some diagnostics:
python tv_downloader_enhanced.py --url "..." --dump-copy
```

#### 4. **Protected/Invite-Only Scripts**

**Symptoms**: `SKIPPED: invite-only` or `SKIPPED: protected`

**Expected behavior**: These scripts cannot be downloaded (source code is not public)

**Detection logic**:
```python
# Looks for explicit "OPEN-SOURCE SCRIPT" indicator
# Skips if "invite-only" or "protected script" text found
```

#### 5. **Unicode/Encoding Errors**

**Symptoms**: Garbled characters in .pine files, `UnicodeEncodeError` in console

**Causes**:
- Windows console (cp1252) vs UTF-8 source
- Raw clipboard data with escape sequences

**Solutions**:
```python
# Script auto-normalizes source code:
# - Decodes \n, \t, \uXXXX escapes
# - Normalizes CRLF → LF
# - Saves as UTF-8 with LF newlines

# For console errors, output is sanitized to console encoding
```

**Detection logic**:
```python
# Skip if:
# - Starts with 'import'
# - AND does NOT contain //@version, indicator(), library(), plot()
```

---

## Advanced Configuration

### Human-Like Behavior Tuning

```python
# Modify delays in EnhancedTVScraper class:

# Mouse movement delay
await self._human_like_delay(100, 500)  # 100-500ms

# Scroll timing
await self.page.wait_for_timeout(random.randint(200, 600))

# Inter-script delay
await self.page.wait_for_timeout(int(delay * 1000))  # Default 2s
```

### Retry Logic Customization

```python
# In download_all() method:
max_attempts = 1 if getattr(self, 'fast_mode', False) else 3

# Recovery actions:
# - Attempt 2: Soft context restart
# - Attempt 3: Full browser restart
```

### User Agent Rotation

```python
# Modify USER_AGENTS list at top of file:
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...',
    # Add your custom user agents here
]
```

---

## Performance Tips

### 1. Fast Mode for Large Collections

```bash
# Use --dump-copy for 3-5x speed increase
python tv_downloader_enhanced.py \
  --url "https://www.tradingview.com/scripts/..." \
  --dump-copy \
  --delay 0.5
```

**Trade-offs**:
- ✅ Faster execution
- ✅ Less diagnostic overhead
- ❌ No diagnostic files for troubleshooting
- ❌ Single retry attempt

### 2. Positional Click for Stable Layouts

```bash
# When downloading from same listing repeatedly
python tv_downloader_enhanced.py \
  --url "https://..." \
  --positional-click \
  --dump-copy
```

**When to use**:
- Same script type/category (consistent layout)
- Stable TradingView UI (no A/B testing)
- High-volume downloads (1000+ scripts)

### 3. Parallel Processing (Advanced)

**Not built-in**, but you can run multiple instances:

```bash
# Terminal 1: Page 1-20
DOWNLOAD_URL="https://www.tradingview.com/scripts/?page=1" \
  python tv_downloader_enhanced.py --max-pages 20

# Terminal 2: Page 21-40
DOWNLOAD_URL="https://www.tradingview.com/scripts/?page=21" \
  python tv_downloader_enhanced.py --max-pages 20
```

**Warning**: May trigger rate limiting or detection

---

## API Integration (Future)

### Programmatic Usage

```python
from tv_downloader_enhanced import EnhancedTVScraper

async def download_scripts():
    scraper = EnhancedTVScraper(
        output_dir='/path/to/output',
        headless=True
    )
    
    await scraper.setup()
    
    try:
        # Single script
        result = await scraper.extract_pine_source(
            'https://www.tradingview.com/script/ABC123-...'
        )
        
        if result.get('source_code'):
            scraper.save_script(result, 'my_category')
        
        # Batch download
        await scraper.download_all(
            'https://www.tradingview.com/scripts/most-popular/',
            max_pages=50,
            delay=2.0
        )
    
    finally:
        await scraper.cleanup()
```

---

## Legal & Ethical Considerations

### Terms of Service

⚠️ **Important**: Review TradingView's Terms of Service before use

- Respect rate limits
- Only download open-source scripts
- Do not redistribute without author permission
- Attribute original authors in any derivative work

### Respectful Scraping

```python
# Built-in protections:
- Default 2s delay between requests
- Skips protected/invite-only scripts
- Detects and respects "open-source" indicators
- Uses standard browser user agents
```

### Data Usage

- Downloaded scripts are for personal/educational use
- Commercial use may require author permission
- Include attribution in any public sharing

---

## Contributing

### Reporting Issues

Include in bug reports:
1. Full command used
2. Error message/traceback
3. Script URL (if single script)
4. Output from `--debug-pages` if available

### Feature Requests

Current roadmap:
- [ ] Async batch processing (parallel downloads)
- [ ] WebSocket-based clipboard monitoring
- [ ] Machine learning-based layout detection
- [ ] Integration with Pine Script linters/formatters
- [ ] Export to other formats (PDF, HTML)

---

## Version History

### Enhanced Version (Current)
- Multi-strategy extraction (clipboard, positional, DOM)
- Stale clipboard detection (SHA-256 hashing)
- Context isolation for batch downloads
- Import-only snippet filtering
- Viewport consistency fixes
- Google login modal handling

### Previous Versions
- Basic copy-button extraction
- Single-context batch processing
- Limited error recovery

---

## License

This tool is provided as-is for educational purposes. Users are responsible for compliance with TradingView's Terms of Service and applicable laws.

---

## Support

For issues, questions, or improvements, refer to:
- Script source code comments
- `--dump-copy-diagnostics` mode for troubleshooting
- `--debug-pages` for verbose logging

---

**Last Updated**: February 2026  
**Script Version**: Enhanced (Multi-Strategy)  
**Tested On**: Ubuntu 24, Windows 11, macOS 14

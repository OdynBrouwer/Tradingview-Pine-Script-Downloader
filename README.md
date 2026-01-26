# TradingView Pine Script Downloader

Automate downloading open-source Pine Script indicators and strategies from TradingView.

## Features

- 📥 **Batch Download**: Download all scripts from any TradingView scripts listing page
- 📄 **Pagination Support**: Automatically handles "Show more" buttons
- 🔐 **Smart Detection**: Identifies and skips protected/invite-only scripts
- 💾 **Progress Saving**: Resume interrupted downloads
- 📊 **Metadata Export**: JSON export of all script metadata
- 🎯 **Multiple Extraction Methods**: Robust source code extraction with fallbacks

## Installation

### 1. Install Python Requirements

```bash
# Clone or download this folder
cd tradingview_scraper

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Verify Installation

```bash
python tv_pinescript_downloader.py --help
```

### Development / Virtual Environment

Follow these steps to create and activate a virtual environment and use it in VS Code.

PowerShell:
```powershell
python -m venv .venv
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process  # if needed (one-time per session)
. .venv\\Scripts\\Activate.ps1
```

CMD:
```
.venv\\Scripts\\activate.bat
```

Git Bash / WSL:
```
source .venv/bin/activate
```

Install dependencies and Playwright browsers:
```bash
pip install -r requirements.txt
python -m playwright install
```

VS Code
- Open the workspace; `.vscode/settings.json` is configured to use `.venv`.
- If not selected: Command Palette → `Python: Select Interpreter` → choose `.venv\\Scripts\\python.exe`.
- The integrated terminal will auto-activate the venv; press F5 or use the Debug panel to run/debug (the provided `Python: Current File` launch configuration uses the integrated terminal).

## Usage

### Basic Usage

**Use the fixed version (recommended):**

```bash
python tv_downloader_fixed.py --url "https://www.tradingview.com/scripts/luxalgo/"
```

### Docker (run headless with Playwright browsers)

A Docker image is provided for running the downloader in an isolated, reproducible container. The image is based on the official Playwright Python image and includes browser binaries.

Build the image locally:

```bash
docker build -t tv-downloader:latest .
```

Run a single download (mount host output dir):

```bash
# Windows (PowerShell):
docker run --rm -v "${PWD}:/app" -v "${PWD}/pinescript_downloads:/app/pinescript_downloads" tv-downloader:latest \
  python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/" --output ./pinescript_downloads --max-pages 5

# Linux/macOS:
docker run --rm -v "$(pwd):/app" -v "$(pwd)/pinescript_downloads:/app/pinescript_downloads" tv-downloader:latest \
  python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/" --output ./pinescript_downloads --max-pages 5
```

Or use docker-compose:

```bash
docker-compose build
docker-compose run --rm downloader python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/" --output ./pinescript_downloads --max-pages 5
```

Notes for Proxmox LXC: enable nesting and run Docker inside the container, or use a full VM for the most reliable Playwright/browser support.

Verify browsers inside the container (quick health check):

```bash
# Run the small verification script inside the image
# Windows (PowerShell):
docker run --rm -v "${PWD}:/app" tv-downloader:latest python scripts/verify_playwright.py

# Linux/macOS:
docker run --rm -v "$(pwd):/app" tv-downloader:latest python scripts/verify_playwright.py
```

If the verification fails with permission errors related to installing browsers, rebuild the image locally (the official Playwright base image includes browsers, so rebuilding ensures binaries are present):

```bash
docker build -t tv-downloader:latest .
```



Download scripts from a specific page (e.g., LuxAlgo scripts):

```bash
python tv_pinescript_downloader.py --url "https://www.tradingview.com/scripts/luxalgo/"
```

### With Options

```bash
# Custom output directory
python tv_pinescript_downloader.py \
    --url "https://www.tradingview.com/scripts/luxalgo/" \
    --output "./my_indicators"

# Limit pages scanned (for large collections)
python tv_pinescript_downloader.py \
    --url "https://www.tradingview.com/scripts/" \
    --max-pages 5

# Show browser window (for debugging)
python tv_pinescript_downloader.py \
    --url "https://www.tradingview.com/scripts/editors-picks/" \
    --visible

# Faster downloads (shorter delay - be respectful!)
python tv_pinescript_downloader.py \
    --url "https://www.tradingview.com/scripts/luxalgo/" \
    --delay 1.5
```

### Enhanced Version (Recommended)

The enhanced version has better source code extraction and progress resuming:

```bash
python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/"

# Resume an interrupted download
python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/"

# Start fresh (ignore previous progress)
python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/" --no-resume
```

## Example URLs

Here are some TradingView pages you can download from:

| Description | URL |
|------------|-----|
| LuxAlgo Scripts | `https://www.tradingview.com/scripts/luxalgo/` |
| Editors' Picks | `https://www.tradingview.com/scripts/editors-picks/` |
| All Scripts | `https://www.tradingview.com/scripts/` |
| Indicators Only | `https://www.tradingview.com/scripts/indicators/` |
| Strategies | `https://www.tradingview.com/scripts/strategies/` |
| By Author | `https://www.tradingview.com/u/USERNAME/#published-scripts` |
| Specific Tag | `https://www.tradingview.com/scripts/volumeprofile/` |

## Output Structure

```
pinescript_downloads/
└── luxalgo/                        # Category folder
    ├── ABC123_Script_Name.pine     # Pine Script files
    ├── DEF456_Another_Script.pine
    ├── ...
    ├── manifest.txt                # Download summary
    ├── metadata.json               # Full metadata (enhanced version)
    └── .progress.json              # Progress file for resuming
```

## Script File Format

Each downloaded `.pine` file includes a header:

```pinescript
// Title: Smart Money Concepts [LuxAlgo]
// Script ID: xyz123
// Author: LuxAlgo
// URL: https://www.tradingview.com/script/xyz123-Smart-Money-Concepts-LuxAlgo/
// Downloaded: 2024-01-15T10:30:00
// Pine Version: 5
// Type: Indicator
//

//@version=5
indicator("Smart Money Concepts [LuxAlgo]", overlay=true)
// ... rest of the script
```

## Command Line Options

### Basic Version (`tv_pinescript_downloader.py`)

| Option | Description | Default |
|--------|-------------|---------|
| `--url`, `-u` | TradingView scripts URL (required) | - |
| `--output`, `-o` | Output directory | `./pinescript_downloads` |
| `--max-pages`, `-p` | Maximum pages to scan | `10` |
| `--delay`, `-d` | Delay between downloads (seconds) | `2.0` |
| `--visible` | Show browser window | `False` |

### Enhanced Version (`tv_downloader_enhanced.py`)

All basic options plus:

| Option | Description | Default |
|--------|-------------|---------|
| `--no-resume` | Start fresh, ignore progress | `False` |

## Limitations

1. **Open Source Only**: Protected and invite-only scripts cannot be downloaded
2. **Rate Limiting**: TradingView may block requests if too fast - use reasonable delays
3. **Dynamic Content**: Some scripts may have complex loading that prevents extraction
4. **Terms of Service**: Respect TradingView's ToS and script authors' licensing

## Troubleshooting

### "No source code found"

Some scripts may be:
- Protected/Invite-only (not downloadable)
- Using complex rendering that prevents extraction
- Try the enhanced version which has more extraction methods

### "Timeout" errors

- Increase the delay: `--delay 3.0`
- Check your internet connection
- TradingView might be temporarily slow

### Browser crashes

```bash
# Reinstall Playwright browsers
playwright install --force chromium
```

### Scripts not loading

Try running with visible browser to debug:

```bash
python tv_downloader_enhanced.py --url "YOUR_URL" --visible
```

## Ethical Usage

- **Respect Authors**: Downloaded scripts retain their original licensing
- **Rate Limiting**: Use reasonable delays between requests
- **Personal Use**: Intended for personal backup/reference
- **Attribution**: Credit original authors when using their code

## License

This tool is provided as-is for educational and personal use. The downloaded scripts belong to their respective authors and are subject to their licensing terms.

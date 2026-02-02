# Run periodic collection and batch processing for TradingView downloads
# Usage: scheduled via Task Scheduler (example provided in repo README)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Split-Path -Parent $ScriptDir
# Run from the repository root so python scripts can be referenced by filename
Set-Location $RepoRoot

# ensure logs folder (keep logs under scripts/ for clarity)
$logDir = Join-Path $ScriptDir 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ('collection_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
$lockFile = Join-Path $logDir 'collection.lock'

# Prevent overlapping runs: if lock exists and is fresh (<14 minutes) exit
if (Test-Path $lockFile) {
    $age = (Get-Date) - (Get-Item $lockFile).LastWriteTime
    if ($age.TotalMinutes -lt 14) {
        "[{0}] Existing run in progress (lock age {1:N1} min). Exiting." -f (Get-Date), $age.TotalMinutes | Tee-Object -FilePath $logFile -Append
        exit 0
    } else {
        # stale lock — remove
        Remove-Item $lockFile -Force
    }
}

# create lock
"{0} - Starting periodic collection" -f (Get-Date) | Tee-Object -FilePath $logFile -Append
New-Item -ItemType File -Path $lockFile -Force | Out-Null

try {
    # Activate virtualenv if present (venv is located at repo root)
    $venvActivate = Join-Path $RepoRoot '.venv\Scripts\Activate.ps1'
    if (Test-Path $venvActivate) {
        "Activating virtualenv: $venvActivate" | Tee-Object -FilePath $logFile -Append
        & $venvActivate | Out-Null
    } else {
        "No virtualenv found at .venv - using system Python" | Tee-Object -FilePath $logFile -Append
    }

    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) { $python = 'python' }

    $commands = @(
        ("$python" + ' batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=strategies&sort=recent_extended&page={n}" --start 1 --end 3 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads'),
        ("$python" + ' batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=libraries&sort=recent_extended&page={n}" --start 1 --end 3 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads'),
        ("$python" + ' batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=indicators&sort=recent_extended&page={n}" --start 1 --end 3 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads'),
        ("$python" + ' batch_pages.py --start 1 --end 3 --suppress-diagnostics --positional-click')
    )

    foreach ($cmd in $commands) {
        $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
        $cmdOut = Join-Path $logDir ("cmd_$ts.out")
        $cmdErr = Join-Path $logDir ("cmd_$ts.err")
        "[{0}] Running: {1}" -f (Get-Date), $cmd | Tee-Object -FilePath $logFile -Append
        # Use cmd.exe /c and wrap the command in quotes to preserve ampersands and other special chars
        $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$cmd`"" -PassThru -Wait -WindowStyle Hidden -WorkingDirectory $RepoRoot -RedirectStandardOutput $cmdOut -RedirectStandardError $cmdErr
        "Output saved to: $cmdOut, Error saved to: $cmdErr" | Tee-Object -FilePath $logFile -Append
        if ($proc.ExitCode -ne 0) {
            "ERROR: Command failed with exit code $($proc.ExitCode): $cmd" | Tee-Object -FilePath $logFile -Append
            # include last few lines of stderr for diagnostics
            if (Test-Path $cmdErr) { Get-Content $cmdErr -Tail 20 | Tee-Object -FilePath $logFile -Append }
        } else {
            "OK: Command succeeded: $cmd" | Tee-Object -FilePath $logFile -Append
        }
    }

    "{0} - Completed periodic collection" -f (Get-Date) | Tee-Object -FilePath $logFile -Append
} catch {
    "Exception: $_" | Tee-Object -FilePath $logFile -Append
} finally {
    # remove lock
    if (Test-Path $lockFile) { Remove-Item $lockFile -Force }
}

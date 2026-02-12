# Run periodic collection and batch processing for TradingView downloads
# Usage: scheduled via Task Scheduler (example provided in repo README)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Split-Path -Parent $ScriptDir
# Run from the repository root so python scripts can be referenced by filename
Set-Location $RepoRoot

# Force Python/console to use UTF-8 to avoid cp1252 encoding errors when output is redirected to files
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ensure logs folder (keep logs under scripts/ for clarity)
$logDir = Join-Path $ScriptDir 'logs' 
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ('collection_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
$lockFile = Join-Path $logDir 'collection.lock'

# Prevent overlapping runs: if lock exists and is fresh (<5 minutes) exit
if (Test-Path $lockFile) {
    $age = (Get-Date) - (Get-Item $lockFile).LastWriteTime
    if ($age.TotalMinutes -lt 5) {
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
        ("$python" + ' batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=strategies&sort=recent_extended&page={n}" --start 1 --end 1 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads'),
        ("$python" + ' batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=libraries&sort=recent_extended&page={n}" --start 1 --end 1 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads'),
        ("$python" + ' batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=indicators&sort=recent_extended&page={n}" --start 1 --end 1 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads'),
        ("$python" + ' batch_pages.py --start 1 --end 1 --suppress-diagnostics --positional-click')
    )

    foreach ($cmd in $commands) {
        $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
        $cmdOut = Join-Path $logDir ("cmd_$ts.out")
        $cmdErr = Join-Path $logDir ("cmd_$ts.err")
        "[{0}] Running: {1}" -f (Get-Date), $cmd | Tee-Object -FilePath $logFile -Append

        # Start the command and enforce a timeout so a stuck child doesn't hang the whole task
        $cmdTimeoutMinutes = 30  # per-command timeout (minutes) - adjust if needed
        # try to start the actual executable (avoid launching via cmd.exe so ExitCode is available)
        $exe = $null; $args = $null
        if ($cmd -match '^\s*"(?<exe>[^"]+)"\s*(?<rest>.*)$') { $exe = $matches['exe']; $args = $matches['rest'] }
        elseif ($cmd -match '^\s*(?<exe>\S+)\s*(?<rest>.*)$') { $exe = $matches['exe']; $args = $matches['rest'] }
        else { $exe = 'cmd.exe'; $args = "/c `"$cmd`"" }

        try {
            $startInfo = Start-Process -FilePath $exe -ArgumentList $args -PassThru -WindowStyle Hidden -WorkingDirectory $RepoRoot -RedirectStandardOutput $cmdOut -RedirectStandardError $cmdErr
            "Output saved to: $cmdOut, Error saved to: $cmdErr (started $exe)" | Tee-Object -FilePath $logFile -Append
        } catch {
            "ERROR: Failed to start process $($exe) $($args): $_" | Tee-Object -FilePath $logFile -Append
            continue
        }

        # If Start-Process returned an object without an Id (some environments), attempt to locate the process by name and recent start time
        if (-not $startInfo -or -not $startInfo.Id) {
            try {
                $procName = Split-Path $exe -Leaf
                $candidate = Get-Process -Name $procName -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -gt (Get-Date).AddMinutes(-5) } | Sort-Object StartTime -Descending | Select-Object -First 1
                if ($candidate) {
                    "Info: matched running process $($candidate.Id) for exe $procName" | Tee-Object -FilePath $logFile -Append
                    $startInfo = $candidate
                } else {
                    "Warning: no candidate process found for $procName (Start-Process did not return an Id)" | Tee-Object -FilePath $logFile -Append
                }
            } catch {
                "Exception while locating candidate process for $($exe): $($_)" | Tee-Object -FilePath $logFile -Append
            }
        }

        if ($startInfo -and $startInfo.Id) {
            "Info: started process Id $($startInfo.Id) (exe $exe)" | Tee-Object -FilePath $logFile -Append
        } else {
            "WARNING: Process started but no process id available for command: $cmd" | Tee-Object -FilePath $logFile -Append
        }

        try {
            # Wait up to the timeout for the process to exit
            Wait-Process -Id $startInfo.Id -Timeout ($cmdTimeoutMinutes * 60)
            # After wait, check if process is still running
            $running = Get-Process -Id $startInfo.Id -ErrorAction SilentlyContinue
            if ($running) {
                "Timeout: command exceeded ${cmdTimeoutMinutes} minutes; attempting to terminate process id ${($startInfo.Id)}" | Tee-Object -FilePath $logFile -Append
                try {
                    Stop-Process -Id $startInfo.Id -Force -ErrorAction Stop
                    "Info: Stop-Process signalled pid ${($startInfo.Id)}" | Tee-Object -FilePath $logFile -Append
                    Start-Sleep -Seconds 2
                    if (Get-Process -Id $startInfo.Id -ErrorAction SilentlyContinue) {
                        "Warning: pid ${($startInfo.Id)} still running after Stop-Process, invoking taskkill /F /T" | Tee-Object -FilePath $logFile -Append
                        try {
                            & cmd.exe /c "taskkill /F /PID $($startInfo.Id) /T" 2>&1 | Out-String | Tee-Object -FilePath $logFile -Append
                            Start-Sleep -Seconds 1
                            if (Get-Process -Id $startInfo.Id -ErrorAction SilentlyContinue) {
                                "ERROR: Failed to terminate process ${($startInfo.Id)}" | Tee-Object -FilePath $logFile -Append
                            } else {
                                "Info: Process ${($startInfo.Id)} terminated by taskkill" | Tee-Object -FilePath $logFile -Append
                            }
                        } catch {
                            "Exception invoking taskkill for pid ${($startInfo.Id)}: $_" | Tee-Object -FilePath $logFile -Append
                        }
                    } else {
                        "Info: Process ${($startInfo.Id)} stopped successfully after Stop-Process" | Tee-Object -FilePath $logFile -Append
                    }
                } catch {
                    "Warning: Stop-Process failed for pid ${($startInfo.Id)}: $_ -- trying taskkill /F /T" | Tee-Object -FilePath $logFile -Append
                    try {
                        & cmd.exe /c "taskkill /F /PID $($startInfo.Id) /T" 2>&1 | Out-String | Tee-Object -FilePath $logFile -Append
                        Start-Sleep -Seconds 1
                        if (Get-Process -Id $startInfo.Id -ErrorAction SilentlyContinue) {
                            "ERROR: Failed to terminate process ${($startInfo.Id)} after taskkill" | Tee-Object -FilePath $logFile -Append
                        } else {
                            "Info: Process ${($startInfo.Id)} terminated by taskkill" | Tee-Object -FilePath $logFile -Append
                        }
                    } catch {
                        "Exception invoking taskkill for pid ${($startInfo.Id)}: $_" | Tee-Object -FilePath $logFile -Append
                    }
                }
                "ERROR: Command timed out and was terminated: ${cmd}" | Tee-Object -FilePath $logFile -Append
            } else {
                # Process finished - retrieve exit code (refresh object first; exit code may not be available until object updated)
                try {
                    $startInfo.Refresh()
                    $exitCode = $startInfo.ExitCode
                } catch {
                    $exitCode = $null
                }

                if ($null -eq $exitCode) {
                    "WARNING: Could not determine exit code for pid ${($startInfo.Id)}: ${cmd}" | Tee-Object -FilePath $logFile -Append
                    if (Test-Path $cmdErr) {
                        "Last 40 lines of stderr (unknown exit code):" | Tee-Object -FilePath $logFile -Append
                        Get-Content $cmdErr -Tail 40 | Tee-Object -FilePath $logFile -Append
                    }
                    # Fallback heuristic: if stderr file is present and non-empty, treat as failure; otherwise assume success
                    try {
                        $errLen = 0
                        if (Test-Path $cmdErr) { $errLen = (Get-Item $cmdErr).Length }
                        if ($errLen -gt 0) {
                            "ERROR: Command likely failed (stderr present) for: ${cmd}" | Tee-Object -FilePath $logFile -Append
                        } else {
                            "OK: No stderr captured; assuming exit code 0 for: ${cmd}" | Tee-Object -FilePath $logFile -Append
                        }
                    } catch {
                        "WARNING: fallback exit detection failed: $($_)" | Tee-Object -FilePath $logFile -Append
                    }
                } elseif ($exitCode -ne 0) {
                    "ERROR: Command failed with exit code ${exitCode}: ${cmd}" | Tee-Object -FilePath $logFile -Append
                    if (Test-Path $cmdErr) { Get-Content $cmdErr -Tail 40 | Tee-Object -FilePath $logFile -Append }
                } else {
                    "OK: Command succeeded: ${cmd} (exit code 0)" | Tee-Object -FilePath $logFile -Append
                }
            }
        } catch {
            "Exception while waiting on process id $($startInfo.Id): $_" | Tee-Object -FilePath $logFile -Append
            # attempt to kill the process if still present
            try { Stop-Process -Id $startInfo.Id -Force -ErrorAction SilentlyContinue } catch {}
        }
    }

    "{0} - Completed periodic collection" -f (Get-Date) | Tee-Object -FilePath $logFile -Append
} catch {
    "Exception: $_" | Tee-Object -FilePath $logFile -Append
} finally {
    # run log cleanup (remove logs older than 4 hours) and record what was removed
    $cleanupScript = Join-Path $ScriptDir 'cleanup_logs.ps1'
    if (Test-Path $cleanupScript) {
        "Running log cleanup (older than 4h) via $cleanupScript" | Tee-Object -FilePath $logFile -Append
        try {
            $removedFiles = & $cleanupScript -LogDir $logDir -MaxAgeHours 4 2>$null
            if ($removedFiles) {
                "Cleanup removed {0} files:" -f ($removedFiles.Length) | Tee-Object -FilePath $logFile -Append
                $removedFiles | ForEach-Object { $_ | Tee-Object -FilePath $logFile -Append }
            } else {
                "Cleanup removed 0 files." | Tee-Object -FilePath $logFile -Append
            }
        } catch {
            "Cleanup exception: $_" | Tee-Object -FilePath $logFile -Append
        }
    } else {
        "Cleanup script not found: $cleanupScript" | Tee-Object -FilePath $logFile -Append
    }

    # remove lock
    if (Test-Path $lockFile) { Remove-Item $lockFile -Force }
}

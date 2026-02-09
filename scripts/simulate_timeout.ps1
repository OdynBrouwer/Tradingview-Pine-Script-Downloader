# Simulate a long-running command and demonstrate timeout/kill behavior
$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$logDir = Join-Path $ScriptDir 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ('collection_sim.log')
# Stop the scheduled task if it's running
try {
    schtasks /End /TN "TV-collection" 2>&1 | Out-Null
    "[{0}] Stopped scheduled task (if running)" -f (Get-Date) | Tee-Object -FilePath $logFile -Append
} catch {
    "[{0}] Could not stop scheduled task: {1}" -f (Get-Date), $_ | Tee-Object -FilePath $logFile -Append
}
# Remove stale lock if present
$lockFile = Join-Path $logDir 'collection.lock'
if (Test-Path $lockFile) {
    "[{0}] Removing stale lock file" -f (Get-Date) | Tee-Object -FilePath $logFile -Append
    Remove-Item $lockFile -Force
}
# Simulated command (long-running)
$cmd = 'ping -n 120 127.0.0.1'
"[{0}] Starting simulated command: {1}" -f (Get-Date), $cmd | Tee-Object -FilePath $logFile -Append
$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList "/c $cmd" -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'sim_out.txt') -RedirectStandardError (Join-Path $logDir 'sim_err.txt')
# Wait with short test timeout (5 seconds) then kill
$testTimeoutSec = 5
$waited = $false
try {
    Wait-Process -Id $proc.Id -Timeout $testTimeoutSec
    $running = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if ($running) {
        "[{0}] Timeout reached ({1}s) - terminating process id {2}" -f (Get-Date), $testTimeoutSec, $proc.Id | Tee-Object -FilePath $logFile -Append
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        "[{0}] Process terminated" -f (Get-Date) | Tee-Object -FilePath $logFile -Append
    } else {
        "[{0}] Process finished within timeout" -f (Get-Date) | Tee-Object -FilePath $logFile -Append
    }
} catch {
    "[{0}] Exception while waiting/killing process: {1}" -f (Get-Date), $_ | Tee-Object -FilePath $logFile -Append
    try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
}
# Log last lines of simulated stdout/stderr
$out = Join-Path $logDir 'sim_out.txt'
$err = Join-Path $logDir 'sim_err.txt'
if (Test-Path $out) { "[{0}] Last stdout lines:" -f (Get-Date) | Tee-Object -FilePath $logFile -Append; Get-Content $out -Tail 20 | Tee-Object -FilePath $logFile -Append }
if (Test-Path $err) { "[{0}] Last stderr lines:" -f (Get-Date) | Tee-Object -FilePath $logFile -Append; Get-Content $err -Tail 20 | Tee-Object -FilePath $logFile -Append }
"[{0}] Simulation complete" -f (Get-Date) | Tee-Object -FilePath $logFile -Append

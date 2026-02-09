# Cleanup old logs older than a given age (default 24 hours)
param(
    [string]$LogDir = "$PSScriptRoot\logs",
    [int]$MaxAgeHours = 24,
    [string[]]$Patterns = @('*.log','*.out','*.err'),
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $LogDir)) { return }

$threshold = (Get-Date).AddHours(-$MaxAgeHours)
$removed = @()

foreach ($pattern in $Patterns) {
    Get-ChildItem -Path $LogDir -Filter $pattern -File | ForEach-Object {
        try {
            if ($_.LastWriteTime -lt $threshold) {
                $removed += $_.FullName
                if (-not $DryRun) { Remove-Item -Path $_.FullName -Force -ErrorAction Stop }
            }
        } catch {
            # ignore individual failures to keep cleanup running
        }
    }
}

# output removed files (one per line) so callers can log them
if ($removed.Count -gt 0) {
    $removed | ForEach-Object { Write-Output $_ }
} else {
    if ($DryRun) { Write-Output "DryRun: no files matched for removal older than $MaxAgeHours hours." }
}

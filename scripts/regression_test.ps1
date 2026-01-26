# Regression test: compare tv_downloader_fixed and tv_downloader_enhanced outputs for a URL
# Usage: . .venv\Scripts\Activate.ps1; ./scripts/regression_test.ps1 -Url "https://www.tradingview.com/scripts/luxalgo/"
param(
  [string]$Url = "https://www.tradingview.com/scripts/luxalgo/",
  [int]$MaxPages = 3
)

$env:PINE_OUTPUT_DIR = ""
$base = Get-Location
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "test_fixed" | Out-Null
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "test_enhanced" | Out-Null

Write-Host "Running fixed downloader..." -ForegroundColor Cyan
python tv_downloader_fixed.py --url $Url --output ./test_fixed --max-pages $MaxPages --visible:$false

Write-Host "Running enhanced downloader..." -ForegroundColor Cyan
python tv_downloader_enhanced.py --url $Url --output ./test_enhanced --no-resume --delay 1.5 --visible:$false

function Count-PineFiles($dir) {
  if (!(Test-Path $dir)) { return 0 }
  return (Get-ChildItem -Recurse -Include *.pine -Path $dir -ErrorAction SilentlyContinue | Measure-Object).Count
}

$fixedCount = Count-PineFiles "$base\test_fixed"
$enhancedCount = Count-PineFiles "$base\test_enhanced"

Write-Host "\nResults:" -ForegroundColor Green
Write-Host "  Fixed downloader:    $fixedCount .pine files" -ForegroundColor Yellow
Write-Host "  Enhanced downloader: $enhancedCount .pine files" -ForegroundColor Yellow

if ($fixedCount -ne $enhancedCount) {
  Write-Host "Counts differ. Inspect ./test_fixed and ./test_enhanced for details." -ForegroundColor Red
} else {
  Write-Host "Counts match." -ForegroundColor Green
}

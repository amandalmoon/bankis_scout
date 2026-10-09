# Windows Task Scheduler example. Local reports DO NOT attach to a ChatGPT task automatically.
# Run from the project root, after configuring KIS_APP_KEY/KIS_APP_SECRET in your own secure environment.
# Configure KIS_SOURCE_DATA_URL only after checking actual provider lineage.
# An API documentation home page is NOT proof of any observation.
$ErrorActionPreference='Stop'
if ([string]::IsNullOrWhiteSpace($env:KIS_SOURCE_DATA_URL)) { throw 'Set KIS_SOURCE_DATA_URL to a verifiable actual data-source URL' }
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
# The workstation must be set to Asia/Seoul and the source snapshot actually available.
$stamp=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
py -m bankis_scout fetch-kis --universe examples/universe.csv --out-data data/real
if ($LASTEXITCODE -ne 0) {throw 'KIS fetch failed: do not publish stale data as current'}
$stamp=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
$old = 'reports/live/intelligence.json'
$previous = @()
if (Test-Path $old) { Copy-Item $old 'reports/live/previous_intelligence.json' -Force; $previous=@('--previous','reports/live/previous_intelligence.json') }
py -m bankis_scout intel-pipeline --data-dir data/real --source-url $env:KIS_SOURCE_DATA_URL --available-at $stamp --ingested-at $stamp --asof $stamp --output reports/live @previous
if ($LASTEXITCODE -ne 0) {throw 'Intelligence pipeline failed; last valid file should not be relabelled current'}
Write-Output 'Review reports/live/intelligence.html locally; ChatGPT schedule does not read this file automatically.'

# Local 07:50 job template, NOT an online ChatGPT automation or an order bot.
# Schedule this script in Windows Task Scheduler if the PC will be on at 07:50.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not $env:KIS_APP_KEY -or -not $env:KIS_APP_SECRET) {
    Write-Error 'KIS_APP_KEY and KIS_APP_SECRET not available. No report was generated.'
    exit 2
}
py -m bankis_scout fetch-kis --universe examples/universe.csv --out-data data/real
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
py -m bankis_scout screen --data-dir data/real --output reports/live
exit $LASTEXITCODE

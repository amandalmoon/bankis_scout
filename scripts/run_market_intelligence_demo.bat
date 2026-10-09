@echo off
setlocal
cd /d "%~dp0.."
py -m bankis_scout demo --output reports/demo
if errorlevel 1 exit /b 1
py -m bankis_scout intel-demo --output reports/demo
if errorlevel 1 exit /b 1
start "" "reports\demo\intelligence.html"
endlocal

@echo off
cd /d "%~dp0.."
py -m bankis_scout screen --data-dir data\real --output reports\live
if errorlevel 1 (
    echo Validation failed or required market data absent. No fake watchlist was generated.
    pause
    exit /b 1
)
start "" "%CD%\reports\live\preopen.html"
pause

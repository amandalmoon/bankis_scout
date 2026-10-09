@echo off
cd /d "%~dp0.."
py -m pip install -e .
py -m bankis_scout demo --output reports\demo
start "" "%CD%\reports\demo\preopen.html"
pause

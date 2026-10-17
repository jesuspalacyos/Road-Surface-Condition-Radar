@echo off
cd /d "%~dp0"
py ice_radar.py
echo.
echo If dependencies are missing, run: py -m pip install -r requirements.txt
pause

@echo off
cd /d "%~dp0"
python --version >nul 2>nul && (set PY=python) || (set PY=py)
%PY% radar_heatmap.py --cli COM4 --data COM3
pause

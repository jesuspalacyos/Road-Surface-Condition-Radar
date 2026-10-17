@echo off
cd /d "%~dp0"
REM Use "python" if it works, otherwise the "py" launcher.
python --version >nul 2>nul && (set PY=python) || (set PY=py)
%PY% ice_radar.py
echo.
echo If dependencies are missing, run: %PY% -m pip install -r requirements.txt
pause

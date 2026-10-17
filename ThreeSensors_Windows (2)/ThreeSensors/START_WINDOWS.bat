@echo off
cd /d "%~dp0"
REM Use "python" if it works, otherwise the "py" launcher.
python --version >nul 2>nul && (set PY=python) || (set PY=py)
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto end
%PY% read_sensors.py
:end
pause

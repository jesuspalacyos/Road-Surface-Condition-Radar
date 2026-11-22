@echo off
setlocal
cd /d "%~dp0"
echo === Water_Ice_Live — radar + ESP32 ===
if not exist .venv\Scripts\python.exe (
    echo Creating Python environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :fail
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo.
echo Available serial devices:
.venv\Scripts\python.exe live.py --list-ports
echo.
set /p CLI=Radar CLI/Application port (example COM4): 
set /p DATA=Radar DATA/Auxiliary port (example COM3): 
set /p SENSOR=ESP32 USB serial port (example COM5, or auto): 
if "%SENSOR%"=="" set "SENSOR=auto"
.venv\Scripts\python.exe live.py --cli "%CLI%" --data "%DATA%" --sensor-port "%SENSOR%"
echo.
echo Press any key to close.
pause >nul
exit /b
:fail
echo Setup failed. See README.md.
pause

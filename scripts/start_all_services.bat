@echo off
echo Stopping OEE Monitoring System...

REM Change to script directory
cd /d "%~dp0"

REM Stop data collector
echo Stopping data collector...
taskkill /F /IM pythonw.exe > nul 2>&1
taskkill /F /IM python.exe > nul 2>&1

REM Stop Docker containers (new command)
echo Stopping Docker containers...
docker compose down

echo.
echo All services stopped.
pause
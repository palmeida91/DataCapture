@echo off
echo Stopping OEE Monitoring System...

REM Stop data collector
taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq data_collector_oee*" > nul 2>&1

REM Stop Docker containers
docker-compose down

echo.
echo All services stopped.
pause
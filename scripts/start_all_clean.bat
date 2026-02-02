@echo off
cls
color 0A
title OEE Monitoring System

echo.
echo  ========================================
echo     OEE MONITORING SYSTEM
echo  ========================================
echo.

REM Change to the script directory to ensure correct context
cd /d "%~dp0"

REM Create logs folder if it doesn't exist
if not exist logs mkdir logs

echo  Starting services...
echo.

REM Start Docker containers using new 'docker compose' command (space, not hyphen)
docker compose up -d > logs\docker_startup.log 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [OK] Database and Grafana started
) else (
    echo  [ERROR] Failed to start Docker services
    echo  [INFO] Check logs\docker_startup.log for details
    echo.
    type logs\docker_startup.log
    pause
    exit /b 1
)

REM Wait for database to initialize
echo  [WAIT] Waiting for database to initialize...
timeout /t 15 /nobreak > nul

REM Start data collector in background
start /B pythonw data_collector_oee.py
if %ERRORLEVEL% EQU 0 (
    echo  [OK] Data collector started
) else (
    echo  [ERROR] Failed to start data collector
)

REM Wait for services to stabilize
timeout /t 5 /nobreak > nul

REM Open Grafana in default browser
start http://localhost:3000
echo  [OK] Grafana opened in browser
echo.
echo  ========================================
echo     APPLICATION RUNNING
echo  ========================================
echo.
echo  Services:
echo    - Database:       Running
echo    - Grafana:        http://localhost:3000
echo    - Data Collector: Running in background
echo.
echo  This window can be minimized or closed.
echo  Closing this window will stop all services.
echo.
pause

REM When user closes window, stop everything
echo.
echo  Shutting down services...

REM Stop Docker containers using new command
docker compose down

REM Stop data collector
taskkill /F /IM pythonw.exe > nul 2>&1
taskkill /F /IM python.exe > nul 2>&1

echo  [OK] All services stopped
timeout /t 2 /nobreak > nul
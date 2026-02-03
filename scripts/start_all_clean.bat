@echo off
cls
color 0A
title OEE Monitoring System

echo.
echo  ========================================
echo     OEE MONITORING SYSTEM
echo  ========================================
echo.

REM Define paths relative to this script location
REM Script is at:  \DataCollection\
REM venv is at:    \DataCollection\venv\
REM Python file:   \DataCollection\DataCapture\
set SCRIPT_DIR=%~dp0
set VENV_ACTIVATE=%SCRIPT_DIR%.venv\Scripts\activate.bat
set PROJECT_DIR=%SCRIPT_DIR%DataCapture\
set COLLECTOR=%PROJECT_DIR%data_collector_oee.py
set LOGS_DIR=%PROJECT_DIR%logs

REM Create logs folder if it doesn't exist
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"

REM Verify paths exist before continuing
if not exist "%VENV_ACTIVATE%" (
    echo  [ERROR] venv not found at: %VENV_ACTIVATE%
    pause
    exit /b 1
)
if not exist "%COLLECTOR%" (
    echo  [ERROR] data_collector_oee.py not found at: %COLLECTOR%
    pause
    exit /b 1
)

REM Change to DataCapture folder (where docker-compose.yml lives)
cd /d "%PROJECT_DIR%"

echo  Starting services...
echo.

REM Start Docker containers
docker compose up -d > "%LOGS_DIR%\docker_startup.log" 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [OK] Database and Grafana started
) else (
    echo  [ERROR] Failed to start Docker services
    type "%LOGS_DIR%\docker_startup.log"
    pause
    exit /b 1
)

REM Wait for database to initialize
echo  [WAIT] Waiting for database to initialize...
timeout /t 15 /nobreak > nul

REM Activate venv and start data collector
call "%VENV_ACTIVATE%"
start /B python "%COLLECTOR%" > "%LOGS_DIR%\collector.log" 2>&1
timeout /t 3 /nobreak > nul

REM Verify data collector is running
tasklist /FI "IMAGE eq python.exe" /FO CSV /NH > nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [OK] Data collector started
) else (
    echo  [ERROR] Data collector failed to start
    echo  [INFO] Check %LOGS_DIR%\collector.log for details
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
echo  Monitoring status (updates every 10s)...
echo  Press CTRL+C to stop all services.
echo.

REM Live monitoring loop
:monitor_loop
cls
color 0A
title OEE Monitoring System

echo.
echo  ========================================
echo     OEE MONITORING SYSTEM - LIVE
echo  ========================================
echo.
echo  Current time: %TIME%
echo.

REM Check Docker containers
echo  --- Docker Services ---
docker compose ps --format "  {{.Name}}: {{.Status}}" 2> nul
echo.

REM Check data collector process
echo  --- Data Collector ---
tasklist /FI "IMAGE eq python.exe" /FO CSV /NH > nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [OK] Data Collector: Running
) else (
    echo  [ERROR] Data Collector: NOT running
    echo  [INFO] Restarting data collector...
    call "%VENV_ACTIVATE%"
    start /B python "%COLLECTOR%" > "%LOGS_DIR%\collector.log" 2>&1
)

echo.
echo  --- Links ---
echo  Grafana: http://localhost:3000
echo.
echo  Press CTRL+C to stop all services.
echo.

REM Wait 10 seconds then loop
timeout /t 10 /nobreak > nul
goto :monitor_loop
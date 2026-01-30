@echo off
cd /d "%~dp0\.."

echo ========================================
echo  Complete OEE Data Collector
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found!
    echo Please install Python 3.11+ 
    pause
    exit /b 1
)

REM Check if config exists
if not exist "config\opcua_nodes_oee.json" (
    echo ERROR: Configuration file not found!
    echo Expected: config\opcua_nodes_oee.json
    pause
    exit /b 1
)

REM Check if certificates exist
if not exist "client_cert.der" (
    echo WARNING: client_cert.der not found!
    echo You may need to generate certificates first.
    echo Run: python generate_certs.py
    pause
)

echo Starting OEE Data Collector...
echo.
python data_collector_oee.py

pause

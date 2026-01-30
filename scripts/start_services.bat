@echo off
cd /d "%~dp0\.."
echo ========================================
echo  Starting Production Monitoring System
echo ========================================
echo.

echo Starting Docker containers...
docker compose up -d

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to start Docker containers
    echo Make sure Docker Desktop is running
    pause
    exit /b 1
)

echo.
echo Waiting for services to be ready (10 seconds)...
timeout /t 10 /nobreak >nul

echo.
echo Services started successfully!
echo.
echo Access Points:
echo   Grafana:   http://localhost:3000 (admin/admin)
echo   Database:  localhost:5432
echo.
echo To start data collection, run:
echo   python data_collector.py
echo.
pause

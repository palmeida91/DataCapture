@echo off
cd /d "%~dp0\.."
echo ========================================
echo  Stopping Production Monitoring System
echo ========================================
echo.

echo Stopping Docker containers...
docker compose stop

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to stop Docker containers
    pause
    exit /b 1
)

echo.
echo Services stopped successfully!
echo Note: Data is preserved. Use start_services.bat to restart.
echo.
pause

@echo off
echo ========================================
echo  OPC UA Connection Diagnostics
echo ========================================
echo.
echo Running comprehensive connection test...
echo This may take 10-20 seconds...
echo.
python data_collector.py --diagnose
echo.
pause

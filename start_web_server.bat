@echo off
cd /d "%~dp0"
set "APP_EXE=%~dp0DuplicateMediaFinder.exe"
if not exist "%APP_EXE%" set "APP_EXE=%~dp0dist\DuplicateMediaFinder\DuplicateMediaFinder.exe"

echo ========================================
echo Duplicate Media Finder - Mobile Access
echo ========================================
echo.
echo On your phone, open one of these PC addresses:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do for /f "tokens=*" %%b in ("%%a") do echo http://%%b:8501
echo Choose the address for the WiFi network shared with this PC.
echo Keep this PC on the same WiFi network.
echo.

if exist "%APP_EXE%" (
    echo Starting the packaged app. Use its tray icon to stop the server.
    start "Duplicate Media Finder" "%APP_EXE%" --mobile
    goto :end
)

if exist "venv\Scripts\python.exe" (
    echo Starting the app from the project virtual environment.
    start "Duplicate Media Finder" venv\Scripts\pythonw.exe tray_launcher.py --mobile
    goto :end
)

set "PYTHON=python"
where py >nul 2>&1
if %errorlevel%==0 set "PYTHON=py -3"

%PYTHON% -c "import streamlit" 2>nul
if errorlevel 1 (
    echo Streamlit is not installed. Run setup_dependencies.bat first.
    pause
    exit /b 1
)

echo.
echo Starting mobile server. Press Ctrl+C to stop.
%PYTHON% -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
goto :end

:end
pause
@echo off
cd /d "%~dp0"
set "PYTHON=python"
if exist "venv\Scripts\python.exe" set "PYTHON=venv\Scripts\python.exe"

%PYTHON% -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed.
    echo Run: %PYTHON% -m pip install -r requirements-build.txt
    pause
    exit /b 1
)

%PYTHON% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name DuplicateMediaFinder ^
    --icon app_icon.ico ^
    --collect-all streamlit ^
    --add-data "app.py;." ^
    --add-data "duplicate_core.py;." ^
    --add-data "file_preview.py;." ^
    --add-data "app_icon.ico;." ^
    tray_launcher.py

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

copy /y start_web_server.bat dist\DuplicateMediaFinder\StartMobile.bat >nul
copy /y WINDOWS_APP_README.txt dist\DuplicateMediaFinder\README_FIRST.txt >nul

echo.
echo Build complete: dist\DuplicateMediaFinder\DuplicateMediaFinder.exe
echo Copy the entire dist\DuplicateMediaFinder folder to the target PC.
echo Run StartMobile.bat in that folder for Android phone access.
pause

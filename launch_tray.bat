@echo off
REM System Tray Launcher for Duplicate Media Finder
REM This batch file activates the virtual environment and starts the system tray launcher

cd /d "%~dp0"

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Starting Duplicate Media Finder System Tray...
python tray_launcher.py
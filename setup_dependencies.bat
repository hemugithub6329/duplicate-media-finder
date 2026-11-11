@echo off
cd /d "%~dp0"
set "PYTHON="
echo Creating the Python virtual environment and installing packages...
echo.

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON=py -3"
    goto :create_venv
)

where python >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON=python"
    goto :create_venv
)

echo ERROR: Python not found. Install Python 3.11 from https://python.org
echo During installation, select "Add python.exe to PATH".
pause
exit /b 1

:create_venv
if not exist "venv\Scripts\python.exe" (
    %PYTHON% -m venv venv
    if errorlevel 1 goto :error
)

echo.
echo Installing and updating Python packages...
venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Setup complete. You can now double-click launch_app.bat.
pause
exit /b 0

:error
echo.
echo ERROR: Setup failed. Check the message above, confirm your internet
echo connection, and try setup_dependencies.bat again.
pause
exit /b 1

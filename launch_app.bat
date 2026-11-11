@echo off
cd /d "%~dp0"
title Duplicate Media Finder

if exist "venv\Scripts\python.exe" (
    call venv\Scripts\activate.bat
    python -m streamlit run app.py
    goto :end
)

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 -m streamlit run app.py
    goto :end
)

where python >nul 2>&1
if %errorlevel%==0 (
    python -m streamlit run app.py
    goto :end
)

echo Python or Streamlit not found.
echo Run setup_dependencies.bat first, or install Python 3.10+.
pause

:end
if errorlevel 1 pause

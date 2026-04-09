@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py student_viewer.py
) else (
    python student_viewer.py
)

if errorlevel 1 (
    echo.
    echo Failed to run student_viewer.py.
    pause
)

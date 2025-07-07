@echo off
cd /d "%~dp0"

if not exist "eP_P.py" (
    echo Error: eP_P.py not found in the current directory
    pause
    exit /b 1
)

python eP_P.py
pause
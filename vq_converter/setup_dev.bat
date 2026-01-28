@echo off
echo ==========================================
echo   PokeyVQ Development Setup (Windows)
echo ==========================================

REM Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python not found! Please install Python 3.8+ and add to PATH.
    pause
    exit /b 1
)

REM Create Venv if not exists
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
) else (
    echo Virtual environment already exists.
)

REM Activate and Install
echo Activating .venv...
call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt

echo.
echo ==========================================
echo   Setup Complete!
echo   To start the GUI:
echo     .venv\Scripts\python -m pokey_vq.gui
echo ==========================================
pause

@echo off
REM ============================================================================
REM POKEY VQ Tracker - Windows Build Script
REM ============================================================================
REM Builds standalone executable using PyInstaller
REM
REM Requirements:
REM   - Python 3.8+ installed and in PATH
REM   - Internet connection (for pip install)
REM   - MADS binary in bin\windows_x86_64\mads.exe
REM
REM Usage:
REM   build.bat           - Build the application
REM   build.bat clean     - Clean build directories
REM   build.bat check     - Check dependencies only
REM ============================================================================

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   POKEY VQ Tracker - Windows Build
echo ============================================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Parse arguments
if "%1"=="clean" goto :clean
if "%1"=="check" goto :check

REM Full build
goto :build

:clean
echo Cleaning build directories...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
echo Done.
if "%2"=="" goto :eof
goto :check

:check
echo.
echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    echo Please install Python 3.8+ from https://python.org
    goto :error
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   Python: %PYVER%

echo.
echo Checking required packages...

REM Check each package
set MISSING=
for %%p in (dearpygui numpy scipy sounddevice pydub PyInstaller) do (
    python -c "import %%p" >nul 2>&1
    if errorlevel 1 (
        echo   [X] %%p - MISSING
        set MISSING=!MISSING! %%p
    ) else (
        echo   [OK] %%p
    )
)

REM Check for vq_converter folder (required for VQ conversion)
echo.
echo Checking VQ converter...
if exist "vq_converter\pokey_vq" (
    echo   [OK] vq_converter folder found
) else (
    echo   [?] vq_converter folder not found
    echo       ^(VQ conversion will not work without it^)
    echo       Place the vq_converter folder alongside the tracker
)

echo.
echo Checking MADS binary...
if exist "bin\windows_x86_64\mads.exe" (
    echo   [OK] bin\windows_x86_64\mads.exe
) else (
    echo   [X] bin\windows_x86_64\mads.exe - MISSING
    echo.
    echo   Download MADS from: http://mads.atari8.info/
    echo   Place mads.exe in: bin\windows_x86_64\
    set MISSING=!MISSING! MADS
)

echo.
echo Checking ASM templates...
if exist "asm\song_player.asm" (
    echo   [OK] asm\ directory found
) else (
    echo   [X] asm\ directory missing
    set MISSING=!MISSING! ASM
)

echo.
if defined MISSING (
    echo ============================================================
    echo   Missing components:%MISSING%
    echo ============================================================
    echo.
    echo To install Python packages:
    echo   pip install dearpygui numpy scipy sounddevice pydub pyinstaller
    echo.
    goto :error
)

echo ============================================================
echo   All checks passed!
echo ============================================================
if "%1"=="check" goto :eof

:build
echo.
echo Installing/updating dependencies...
pip install --quiet --upgrade dearpygui numpy scipy sounddevice pydub pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    goto :error
)

echo.
echo Building standalone executable...
echo.

pyinstaller tracker.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    goto :error
)

echo.
echo ============================================================
echo   BUILD SUCCESSFUL!
echo ============================================================
echo.

if exist "dist\POKEY_VQ_Tracker.exe" (
    for %%f in ("dist\POKEY_VQ_Tracker.exe") do (
        echo   Output: %%~ff
        echo   Size:   %%~zf bytes
    )
    echo.
    echo   To run: dist\POKEY_VQ_Tracker.exe
)

echo.
goto :eof

:error
echo.
echo Build failed. Please fix the issues above.
exit /b 1

:eof

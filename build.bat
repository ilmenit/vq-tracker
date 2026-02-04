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
REM   build.bat dist      - Build AND create distribution folder
REM   build.bat clean     - Clean build directories
REM   build.bat check     - Check dependencies only
REM   build.bat install   - Install dependencies only
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
if "%1"=="clean" goto :do_clean
if "%1"=="check" goto :do_check_only
if "%1"=="install" goto :do_install
if "%1"=="dist" goto :do_dist
if "%1"=="help" goto :do_help
if "%1"=="-help" goto :do_help
if "%1"=="/?" goto :do_help

REM Default: full build
goto :do_build

REM ============================================================================
:do_help
REM ============================================================================
echo Usage: build.bat [command]
echo.
echo Commands:
echo   (none)    Build executable only
echo   dist      Build AND create distribution folder
echo   clean     Clean build directories
echo   check     Check dependencies only
echo   install   Install Python dependencies
echo   help      Show this help
echo.
exit /b 0

REM ============================================================================
:do_clean
REM ============================================================================
echo Cleaning build directories...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "release" rmdir /s /q "release"
for %%f in (POKEY_VQ_Tracker_*.zip) do del "%%f" 2>nul
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
echo Done.
exit /b 0

REM ============================================================================
:do_install
REM ============================================================================
echo Installing dependencies...
python -m pip install --upgrade pip
if !errorlevel! neq 0 (
    echo [ERROR] pip upgrade failed
    exit /b 1
)
python -m pip install dearpygui numpy scipy sounddevice pydub soundfile pyinstaller
if !errorlevel! neq 0 (
    echo [ERROR] Package installation failed
    exit /b 1
)
echo.
echo Dependencies installed.
exit /b 0

REM ============================================================================
:do_check_only
REM ============================================================================
call :check_all
if !errorlevel! neq 0 exit /b 1
exit /b 0

REM ============================================================================
:do_build
REM ============================================================================
call :check_all
if !errorlevel! neq 0 (
    echo.
    echo Please fix the issues above before building.
    exit /b 1
)

echo.
echo Installing/updating dependencies...
python -m pip install --quiet --upgrade dearpygui numpy scipy sounddevice pydub soundfile pyinstaller
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install dependencies
    exit /b 1
)

echo.
echo Building standalone executable...
echo.

python -m PyInstaller tracker.spec --noconfirm --clean
if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Build failed!
    exit /b 1
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
    echo.
    echo   To create a complete distribution folder, run:
    echo     build.bat dist
)

echo.
exit /b 0

REM ============================================================================
:do_dist
REM ============================================================================
call :check_all
if !errorlevel! neq 0 (
    echo.
    echo Please fix the issues above before building.
    exit /b 1
)

echo.
echo Installing/updating dependencies...
python -m pip install --quiet --upgrade dearpygui numpy scipy sounddevice pydub soundfile pyinstaller
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install dependencies
    exit /b 1
)

echo.
echo Building and creating distribution...
echo.

python build_release.py --dist
if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Build failed!
    exit /b 1
)

exit /b 0


REM ============================================================================
REM SUBROUTINE: check_all
REM Returns errorlevel 0 = OK, 1 = missing components
REM ============================================================================
:check_all
echo Checking Python...
python --version >nul 2>&1
if !errorlevel! neq 0 (
    echo   [ERROR] Python not found in PATH
    echo   Please install Python 3.8+ from https://python.org
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   Python: %PYVER%

echo.
echo Checking required packages...

set MISSING=
call :check_pkg dearpygui
call :check_pkg numpy
call :check_pkg scipy
call :check_pkg sounddevice
call :check_pkg soundfile
call :check_pkg pydub
call :check_pkg PyInstaller

REM Check for vq_converter folder
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
    set "MISSING=!MISSING! MADS"
)

echo.
echo Checking FFmpeg (optional)...
if exist "bin\windows_x86_64\ffmpeg.exe" (
    echo   [OK] ffmpeg.exe found - MP3/OGG/FLAC import enabled
) else (
    echo   [?] ffmpeg.exe not found - only WAV import available
    echo       Download from: https://www.gyan.dev/ffmpeg/builds/
    echo       Extract ffmpeg.exe to: bin\windows_x86_64\
)

echo.
echo Checking ASM templates...
if exist "asm\song_player.asm" (
    echo   [OK] asm\ directory found
) else (
    echo   [X] asm\ directory missing
    set "MISSING=!MISSING! ASM"
)

echo.
echo Checking samples...
if exist "samples" (
    echo   [OK] samples\ directory found
) else (
    echo   [?] samples\ directory not found ^(optional^)
)

echo.
if defined MISSING (
    echo ============================================================
    echo   Missing components:%MISSING%
    echo ============================================================
    echo.
    echo To install Python packages:
    echo   python -m pip install dearpygui numpy scipy sounddevice pydub soundfile pyinstaller
    echo.
    exit /b 1
)

echo ============================================================
echo   All checks passed!
echo ============================================================
exit /b 0


REM ============================================================================
REM SUBROUTINE: check_pkg <package_name>
REM Checks if a Python package is importable
REM ============================================================================
:check_pkg
python -c "import %~1" >nul 2>&1
if !errorlevel! neq 0 (
    echo   [X] %~1 - MISSING
    set "MISSING=!MISSING! %~1"
) else (
    echo   [OK] %~1
)
exit /b 0

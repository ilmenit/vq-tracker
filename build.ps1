# ============================================================================
# POKEY VQ Tracker - Windows PowerShell Build Script
# ============================================================================
# Builds standalone executable using PyInstaller
#
# Requirements:
#   - Python 3.8+ installed and in PATH
#   - Internet connection (for pip install)
#   - MADS binary in bin\windows_x86_64\mads.exe
#
# Usage:
#   .\build.ps1           - Build the application
#   .\build.ps1 -Dist     - Build AND create distribution folder
#   .\build.ps1 -Clean    - Clean build directories
#   .\build.ps1 -Check    - Check dependencies only
#   .\build.ps1 -Install  - Install dependencies only
#
# If you get execution policy error, run:
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# ============================================================================

param(
    [switch]$Clean,
    [switch]$Check,
    [switch]$Install,
    [switch]$Dist,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# Colors
function Write-OK { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail { param($msg) Write-Host "  [X] $msg" -ForegroundColor Red }
function Write-Warn { param($msg) Write-Host "  [?] $msg" -ForegroundColor Yellow }
function Write-Header { param($msg) Write-Host "`n$msg" -ForegroundColor Cyan }

# Change to script directory
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  POKEY VQ Tracker - Windows PowerShell Build" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($Help) {
    Write-Host "Usage: .\build.ps1 [options]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Clean    Remove build directories"
    Write-Host "  -Check    Check dependencies only"
    Write-Host "  -Install  Install Python dependencies"
    Write-Host "  -Dist     Build AND create distribution folder"
    Write-Host "  -Help     Show this help"
    Write-Host ""
    Write-Host "No options: Build executable only"
    exit 0
}

# Clean
function Clean-Build {
    Write-Host "Cleaning build directories..."
    if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
    if (Test-Path "release") { Remove-Item -Recurse -Force "release" }
    Get-ChildItem -Filter "POKEY_VQ_Tracker_*.zip" | Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Done."
}

# Check Python
function Find-Python {
    Write-Header "Checking Python..."
    
    try {
        $pyver = python --version 2>&1
        Write-Host "  Python: $pyver"
        return $true
    }
    catch {
        Write-Fail "Python not found in PATH"
        Write-Host "  Please install Python 3.8+ from https://python.org"
        return $false
    }
}

# Check packages
function Check-Dependencies {
    Write-Header "Checking required packages..."
    
    $missing = @()
    $packages = @("dearpygui", "numpy", "scipy", "sounddevice", "pydub", "soundfile", "PyInstaller")
    
    foreach ($pkg in $packages) {
        # Suppress stderr warnings (e.g., pydub's ffmpeg warning)
        $env:PYTHONWARNINGS = "ignore"
        try {
            $null = python -c "import $pkg" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-OK $pkg
            }
            else {
                Write-Fail "$pkg - MISSING"
                $missing += $pkg
            }
        }
        catch {
            Write-Fail "$pkg - MISSING"
            $missing += $pkg
        }
        finally {
            $env:PYTHONWARNINGS = ""
        }
    }
    
    # Check for vq_converter folder (required for VQ conversion)
    Write-Header "Checking VQ converter..."
    if (Test-Path "vq_converter\pokey_vq") {
        Write-OK "vq_converter folder found"
    }
    else {
        Write-Warn "vq_converter folder not found"
        Write-Host "      (VQ conversion will not work without it)"
        Write-Host "      Place the vq_converter folder alongside the tracker"
    }
    
    Write-Header "Checking MADS binary..."
    $madsPath = "bin\windows_x86_64\mads.exe"
    if (Test-Path $madsPath) {
        Write-OK $madsPath
    }
    else {
        Write-Fail "$madsPath - MISSING"
        Write-Host ""
        Write-Host "  Download MADS from: http://mads.atari8.info/"
        Write-Host "  Place mads.exe in: bin\windows_x86_64\"
        $missing += "MADS"
    }
    
    Write-Header "Checking FFmpeg (optional)..."
    $ffmpegPath = "bin\windows_x86_64\ffmpeg.exe"
    if (Test-Path $ffmpegPath) {
        Write-OK "ffmpeg.exe found - MP3/OGG/FLAC import enabled"
    }
    else {
        Write-Warn "ffmpeg.exe not found - only WAV import available"
        Write-Host "      Download from: https://www.gyan.dev/ffmpeg/builds/"
        Write-Host "      Extract ffmpeg.exe to: bin\windows_x86_64\"
    }
    
    Write-Header "Checking ASM templates..."
    if (Test-Path "asm\song_player.asm") {
        Write-OK "asm\ directory found"
    }
    else {
        Write-Fail "asm\ directory missing"
        $missing += "ASM"
    }
    
    Write-Header "Checking samples..."
    if (Test-Path "samples") {
        $sampleCount = (Get-ChildItem -Path "samples" -Include "*.wav","*.mp3" -File).Count
        Write-OK "samples\ directory found ($sampleCount files)"
    }
    else {
        Write-Warn "samples\ directory not found (optional)"
    }
    
    Write-Header "Checking MOD files..."
    if (Test-Path "mods") {
        $modCount = (Get-ChildItem -Path "mods" -Include "*.mod","*.MOD" -File).Count
        Write-OK "mods\ directory found ($modCount files)"
    }
    else {
        Write-Warn "mods\ directory not found (optional)"
    }
    
    Write-Host ""
    if ($missing.Count -gt 0) {
        Write-Host "============================================================" -ForegroundColor Red
        Write-Host "  Missing components: $($missing -join ', ')" -ForegroundColor Red
        Write-Host "============================================================" -ForegroundColor Red
        Write-Host ""
        Write-Host "To install Python packages:"
        Write-Host "  pip install dearpygui numpy scipy sounddevice pydub soundfile pyinstaller"
        Write-Host ""
        return $false
    }
    
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  All checks passed!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    return $true
}

# Install dependencies
function Install-Dependencies {
    Write-Header "Installing dependencies..."
    python -m pip install --upgrade pip
    python -m pip install dearpygui numpy scipy sounddevice pydub soundfile pyinstaller
    Write-Host ""
    Write-Host "Dependencies installed."
}

# Build executable only
function Build-App {
    Write-Header "Installing/updating dependencies..."
    python -m pip install --quiet --upgrade dearpygui numpy scipy sounddevice pydub soundfile pyinstaller
    
    Write-Header "Building standalone executable..."
    Write-Host ""
    
    python -m PyInstaller tracker.spec --noconfirm --clean
    
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed!"
    }
    
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  BUILD SUCCESSFUL!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    
    $exePath = "dist\POKEY_VQ_Tracker.exe"
    if (Test-Path $exePath) {
        $size = (Get-Item $exePath).Length / 1MB
        Write-Host "  Output: $((Resolve-Path $exePath).Path)"
        Write-Host "  Size:   $([math]::Round($size, 1)) MB"
        Write-Host ""
        Write-Host "  To run: .\$exePath"
        Write-Host ""
        Write-Host "  To create a complete distribution folder, run:"
        Write-Host "    .\build.ps1 -Dist"
    }
    
    Write-Host ""
}

# Build and create distribution
function Build-Dist {
    Write-Header "Installing/updating dependencies..."
    python -m pip install --quiet --upgrade dearpygui numpy scipy sounddevice pydub soundfile pyinstaller
    
    Write-Header "Building and creating distribution..."
    Write-Host ""
    
    python build_release.py --dist
    
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed!"
    }
}

# Main
try {
    if ($Clean) {
        Clean-Build
        if (-not ($Check -or $Install -or $Dist)) { exit 0 }
    }
    
    if (-not (Find-Python)) { exit 1 }
    
    if ($Install) {
        Install-Dependencies
        exit 0
    }
    
    if ($Check) {
        if (Check-Dependencies) { exit 0 } else { exit 1 }
    }
    
    if ($Dist) {
        if (Check-Dependencies) {
            Build-Dist
        }
        else {
            Write-Host ""
            Write-Host "Please fix the issues above before building."
            exit 1
        }
        exit 0
    }
    
    # Default: Build executable only
    if (Check-Dependencies) {
        Build-App
    }
    else {
        Write-Host ""
        Write-Host "Please fix the issues above before building."
        exit 1
    }
}
catch {
    Write-Host ""
    Write-Host "ERROR: $_" -ForegroundColor Red
    exit 1
}

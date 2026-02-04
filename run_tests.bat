@echo off
REM Run POKEY VQ Tracker test suite
REM Usage: run_tests.bat [options]
REM   run_tests.bat              - run all tests
REM   run_tests.bat -v           - verbose output
REM   run_tests.bat test_name    - run specific test file (without .py)

setlocal

if "%~1"=="" (
    python -m unittest discover -s tests -v
) else if "%~1"=="-v" (
    python -m unittest discover -s tests -v
) else (
    python -m unittest tests.%~1 -v
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo TESTS FAILED
    exit /b 1
) else (
    echo.
    echo ALL TESTS PASSED
)

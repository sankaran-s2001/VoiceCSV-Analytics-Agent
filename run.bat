@echo off
setlocal enabledelayedexpansion

:: =========================================================================
:: VoiceCSV Analytics Agent - Windows One-Click Launcher
:: =========================================================================

title VoiceCSV Analytics Agent

:: 1. Ensure working directory is project root
cd /d "%~dp0"

echo =========================================================================
echo               VoiceCSV Analytics Agent - Quick Launcher
echo =========================================================================
echo.

:: 2. Check Python availability
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not found in your system PATH.
    echo Please install Python 3.10 or newer from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: 3. Check or create Python virtual environment (.venv)
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment (.venv)...
    python -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [*] Virtual environment created successfully.
) else (
    echo [*] Using existing virtual environment (.venv).
)

:: 4. Check configuration file (.env)
if not exist ".env" (
    if exist ".env.example" (
        echo [*] No .env file found. Creating from .env.example template...
        copy ".env.example" ".env" >nul
        echo [NOTE] Created .env with default settings.
        echo [NOTE] Please edit .env to add your GOOGLE_API_KEY for full AI analytics.
        echo.
    )
)

:: 5. Install / update dependencies
echo [*] Checking dependencies...
".venv\Scripts\pip.exe" install -q -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install required Python dependencies.
    echo Please check your internet connection or run:
    echo   .\.venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: 6. Launch Application Supervisor
echo [*] Starting VoiceCSV Analytics Agent...
echo [*] Press Ctrl+C in this terminal at any time to cleanly stop the server.
echo.

".venv\Scripts\python.exe" launcher.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [INFO] Server stopped or exited with status code %ERRORLEVEL%.
)

echo.
pause

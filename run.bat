@echo off
setlocal enabledelayedexpansion

REM =========================================================================
REM VoiceCSV Analytics Agent - Windows One-Click Launcher
REM Production-Ready, Beginner-Proof Startup Script
REM =========================================================================

title VoiceCSV Analytics Agent - Launcher

REM 1. Ensure working directory is strictly project root
cd /d "%~dp0"

echo =========================================================================
echo               VoiceCSV Analytics Agent - Windows Launcher
echo =========================================================================
echo.

REM -------------------------------------------------------------------------
REM 2. Multi-Layer Python Detection
REM    Layer A: Check 'python' in PATH and verify it is executable
REM    Layer B: Check Windows Python Launcher 'py -3'
REM    Layer C: Check standard default install paths (if PATH was not set)
REM -------------------------------------------------------------------------
set "PYTHON_CMD="

REM Test standard 'python'
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

REM Test Windows Python Launcher 'py'
if "%PYTHON_CMD%"=="" (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=py -3"
    )
)

REM Check common standard install paths in case Python was installed without 'Add to PATH'
if "%PYTHON_CMD%"=="" (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
        "C:\Program Files\Python310\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
    ) do (
        if "!PYTHON_CMD!"=="" (
            if exist %%P (
                %%P -c "import sys" >nul 2>&1
                if not errorlevel 1 set "PYTHON_CMD=%%~P"
            )
        )
    )
)

REM If Python is still not found, provide crystal-clear guidance
if "%PYTHON_CMD%"=="" (
    echo [ERROR] Python is not installed or could not be found on this computer.
    echo.
    echo VoiceCSV Analytics Agent requires Python 3.10 or newer.
    echo.
    echo Quick Installation Options:
    echo.
    echo   Option 1 - Automated via Windows Package Manager [Recommended]:
    echo     Open Command Prompt or PowerShell and run:
    echo       winget install Python.Python.3.11
    echo.
    echo   Option 2 - Manual Download:
    echo     1. Visit: https://www.python.org/downloads/
    echo     2. Download Python 3.10, 3.11, or 3.12 installer.
    echo     3. IMPORTANT: Check "Add Python to PATH" during installation.
    echo     4. Re-run this run.bat file after installation completes.
    echo.
    pause
    exit /b 1
)

REM -------------------------------------------------------------------------
REM 3. Verify Python Version (Must be >= 3.10)
REM -------------------------------------------------------------------------
%PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Incompatible Python version detected.
    for /f "tokens=*" %%v in ('%PYTHON_CMD% --version 2^>^&1') do echo   Current Version: %%v
    echo.
    echo VoiceCSV Analytics Agent requires Python 3.10 or newer [3.10, 3.11, or 3.12 recommended].
    echo Please install a compatible Python version from https://www.python.org/downloads/
    echo Remember to check "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('%PYTHON_CMD% --version 2^>^&1') do echo [*] System Python: %%v

REM -------------------------------------------------------------------------
REM 4. Self-Healing Virtual Environment (.venv)
REM    Handles fresh setup and auto-repairs stale/copied virtual environments
REM -------------------------------------------------------------------------
set "RECREATE_VENV=0"
if exist ".venv\Scripts\python.exe" (
    REM Test if the existing venv is actually functional
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo [WARNING] Existing virtual environment in .venv is broken or was copied from another PC.
        echo [*] Re-creating virtual environment for this computer...
        set "RECREATE_VENV=1"
    )
) else (
    set "RECREATE_VENV=1"
)

if "!RECREATE_VENV!"=="1" (
    if exist ".venv" (
        echo [*] Cleaning stale virtual environment...
        rmdir /s /q .venv >nul 2>&1
    )
    echo [*] Setting up isolated Python virtual environment in .venv...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to create virtual environment.
        echo Please ensure you have write permissions in this folder:
        echo   %~dp0
        echo.
        pause
        exit /b 1
    )
    echo [*] Virtual environment created successfully.
    set "NEW_VENV=1"
) else (
    echo [*] Virtual environment verified [.venv].
    set "NEW_VENV=0"
)

REM -------------------------------------------------------------------------
REM 5. Smart Dependency Verification (Fast Launch: Skips if Already Satisfied)
REM -------------------------------------------------------------------------
if not exist "requirements.txt" (
    echo [ERROR] 'requirements.txt' was not found in the project directory.
    echo Please make sure all project files are extracted properly.
    echo.
    pause
    exit /b 1
)

set "NEED_DEPS=0"
if "!NEW_VENV!"=="1" set "NEED_DEPS=1"
if not exist ".venv\.installed_requirements" set "NEED_DEPS=1"

REM Verify core packages import cleanly
if "!NEED_DEPS!"=="0" (
    ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, pandas, google.genai, dotenv, pydantic" >nul 2>&1
    if errorlevel 1 set "NEED_DEPS=1"
)

REM If requirements.txt has changed compared to our marker, trigger re-installation
if "!NEED_DEPS!"=="0" (
    fc /b requirements.txt ".venv\.installed_requirements" >nul 2>&1
    if errorlevel 1 set "NEED_DEPS=1"
)

if "!NEED_DEPS!"=="1" (
    echo [*] Installing required Python dependencies from requirements.txt...
    echo     [This only runs on initial setup or when requirements change]
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install required Python packages from requirements.txt.
        echo Please check your internet connection, or try running manually:
        echo   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    copy /y requirements.txt ".venv\.installed_requirements" >nul 2>&1
    echo [*] Dependencies installed and verified.
) else (
    echo [*] Dependencies verified. Ready to launch.
)

REM -------------------------------------------------------------------------
REM 6. Manage Configuration File (.env) and Validate API Key
REM -------------------------------------------------------------------------
if not exist ".env" (
    if exist ".env.example" (
        echo [*] Initializing .env configuration from .env.example...
        copy ".env.example" ".env" >nul
    ) else (
        echo [*] Generating default .env configuration...
        (
            echo # Google Gemini API configuration
            echo GOOGLE_API_KEY=
            echo GEMINI_MODEL=gemini-3.1-flash-lite
            echo.
            echo # Database configuration
            echo SQLITE_DB_PATH=data/analytics.db
            echo.
            echo # Server configuration
            echo HOST=127.0.0.1
            echo PORT=8000
        ) > ".env"
    )
    echo [*] Created .env file.
)

REM Check if GOOGLE_API_KEY is configured
".venv\Scripts\python.exe" -c "from backend.config import settings; import sys; sys.exit(0 if settings.is_gemini_configured else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo -------------------------------------------------------------------------
    echo [NOTE] Google Gemini API Key is not yet configured in your .env file.
    echo        - Get your free Gemini API key: https://aistudio.google.com/app/apikey
    echo        - Open '.env' in Notepad and set:
    echo            GOOGLE_API_KEY=your_actual_api_key_here
    echo.
    echo        VoiceCSV will still launch so you can explore datasets, schemas,
    echo        and table relationships offline!
    echo -------------------------------------------------------------------------
    echo.
)

REM -------------------------------------------------------------------------
REM 7. Launch Application Supervisor (launcher.py)
REM -------------------------------------------------------------------------
echo [*] Launching VoiceCSV Analytics Agent...
echo [*] Press Ctrl+C in this terminal window at any time to cleanly stop the server.
echo.

".venv\Scripts\python.exe" launcher.py

if errorlevel 1 (
    echo.
    echo [INFO] Application exited with status code %ERRORLEVEL%.
    echo.
    echo Press any key to close this window...
    pause >nul
)

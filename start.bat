@echo off
setlocal
chcp 65001 >nul 2>&1
title TikTok Scraper

echo ========================================
echo   TikTok Scraper - Environment Setup
echo ========================================
echo.

rem Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found. Please install Python 3.10 or newer.
    echo Download: https://www.python.org/downloads/
    echo During installation, enable "Add Python to PATH".
    pause
    exit /b 1
)

echo [1/4] Python detected
python --version

rem Create virtual environment on first run
if not exist ".venv" (
    echo.
    echo [2/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [2/4] Virtual environment already exists
)

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] Virtual environment is incomplete. Please delete .venv and run this file again.
    pause
    exit /b 1
)

set "NEED_INSTALL=0"
if not exist ".venv\.deps_installed" set "NEED_INSTALL=1"
"%PY%" -c "import fastapi, uvicorn, websockets, playwright, httpx" >nul 2>&1
if errorlevel 1 set "NEED_INSTALL=1"

rem Install dependencies when missing or incomplete
if "%NEED_INSTALL%"=="1" (
    echo.
    echo [3/4] Installing or repairing dependencies. This may take a few minutes...
    "%PY%" -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies. Please check your network.
        pause
        exit /b 1
    )

    rem Install bundled CloakBrowser package
    "%PY%" -m pip install -e . -q 2>nul

    echo.
    echo [3/4] Downloading browser binary. This is about 200 MB on first run...
    "%PY%" -c "from cloakbrowser import ensure_binary; ensure_binary()"
    if errorlevel 1 (
        echo [ERROR] Failed to download browser. Please check your network.
        pause
        exit /b 1
    )

    echo done> .venv\.deps_installed
) else (
    echo [3/4] Dependencies already installed
)

rem Start service
echo.
echo [4/4] Starting service...
echo ========================================
echo.
echo   Open http://localhost:8000 in your browser
echo   Press Ctrl+C to stop the service
echo.
echo ========================================
echo.

"%PY%" server.py

pause

@echo off
title TDX Stock Screener - Install Dependencies
setlocal enabledelayedexpansion

:: ============================================================
::  install_deps.bat - Auto install Python dependencies
::  Double-click to run, or run from command line.
:: ============================================================

echo ============================================================
echo      TDX Stock Screener - Python Dependency Installer
echo ============================================================
echo.

:: ---------- Step 1: Detect Python ----------
echo [1/4] Detecting Python...
echo.

set PY=

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY=python
    goto :found_python
)

python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY=python3
    goto :found_python
)

py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY=py
    goto :found_python
)

echo [FAIL] Python not found. Please install Python 3.8 or later.
echo.
echo    Download: https://www.python.org/downloads/
echo.
echo    Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:found_python
%PY% --version
echo [OK] Using: %PY%
echo.

:: ---------- Step 2: Detect pip ----------
echo [2/4] Detecting pip...
echo.

%PY% -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] pip not found. Attempting to install pip...
    echo.
    %PY% -m ensurepip --upgrade >nul 2>&1
    if !errorlevel! neq 0 (
        echo [FAIL] Could not install pip automatically. Manual steps:
        echo    1. Download https://bootstrap.pypa.io/get-pip.py
        echo    2. Run: %PY% get-pip.py
        pause
        exit /b 1
    )
)

%PY% -m pip --version
echo [OK] pip is ready.
echo.

:: ---------- Step 3: Upgrade pip (prevent old-version issues) ----------
echo [3/4] Upgrading pip...
%PY% -m pip install --upgrade pip -q
echo [OK] pip updated.
echo.

:: ---------- Step 4: Install dependencies ----------
echo [4/4] Installing required packages...
echo.

set INSTALL_OK=0

echo   --- pandas ---
%PY% -m pip install "pandas>=1.5.0"
if %errorlevel% equ 0 ( set /a INSTALL_OK+=1 ) else ( echo   [WARN] pandas install failed )

echo.
echo   --- numpy ---
%PY% -m pip install "numpy>=1.23.0"
if %errorlevel% equ 0 ( set /a INSTALL_OK+=1 ) else ( echo   [WARN] numpy install failed )

echo.
echo   --- openpyxl ---
%PY% -m pip install "openpyxl>=3.0.0"
if %errorlevel% equ 0 ( set /a INSTALL_OK+=1 ) else ( echo   [WARN] openpyxl install failed (CSV/.blk export still works) )

echo.
echo ============================================================
if %INSTALL_OK% equ 3 (
    echo [OK] All %INSTALL_OK%/3 packages installed successfully.
    echo.
    echo    Now run:  %PY% main.py --verbose
) else (
    echo [DONE] Installed %INSTALL_OK%/3 packages. Check errors above.
    echo.
    echo    If network is slow, try mirror:
    echo      %PY% -m pip install pandas numpy openpyxl -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo ============================================================
echo.

:: ---------- Show final versions ----------
echo ----------------------------------------
echo Installed package versions:
%PY% -c "import pandas; print('  pandas ', pandas.__version__)"
%PY% -c "import numpy; print('  numpy  ', numpy.__version__)"
%PY% -c "import openpyxl; print('  openpyxl', openpyxl.__version__)" 2>nul || echo   openpyxl (not installed)
echo ----------------------------------------

echo.
pause

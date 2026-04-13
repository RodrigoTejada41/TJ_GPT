@echo off
setlocal

set "PYTHON_EXE="
if exist .python_path set /p PYTHON_EXE=<.python_path
if not defined PYTHON_EXE if exist "%USERPROFILE%\python.exe" set "PYTHON_EXE=%USERPROFILE%\python.exe"
if not defined PYTHON_EXE for /f "delims=" %%i in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\python.exe" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
if not defined PYTHON_EXE for /f "delims=" %%i in ('dir /b /s "%USERPROFILE%\AppData\Local\Programs\Python\python.exe" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
if not defined PYTHON_EXE (
    echo No Python 3 interpreter found. Install Python 3.10+ first.
    exit /b 1
)

if not exist .venv (
    "%PYTHON_EXE%" -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        exit /b 1
    )
)

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo Virtual environment python not found.
    exit /b 1
)

"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Base dependency installation failed.
    exit /b 1
)
"%VENV_PY%" -m pip install -r requirements-optional.txt
if errorlevel 1 (
    echo Optional packages could not be installed. The app will still run with fallbacks.
)

> .python_path echo %PYTHON_EXE%

echo Base install complete.
echo Optional packages:
echo   "%VENV_PY%" -m pip install -r requirements-optional.txt

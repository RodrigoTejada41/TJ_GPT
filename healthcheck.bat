@echo off
setlocal

if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe smoke_test.py
    exit /b %errorlevel%
)

set "PYTHON_EXE="
if exist .python_path set /p PYTHON_EXE=<.python_path
if not defined PYTHON_EXE if exist "%USERPROFILE%\python.exe" set "PYTHON_EXE=%USERPROFILE%\python.exe"
if not defined PYTHON_EXE for /f "delims=" %%i in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\python.exe" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
if not defined PYTHON_EXE for /f "delims=" %%i in ('dir /b /s "%USERPROFILE%\AppData\Local\Programs\Python\python.exe" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
if not defined PYTHON_EXE (
    echo Python 3 is not installed or not found.
    exit /b 1
)

"%PYTHON_EXE%" smoke_test.py

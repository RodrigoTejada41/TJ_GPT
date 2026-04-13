$ErrorActionPreference = "Stop"
. $PSScriptRoot\python_tools.ps1

if (Test-Path ".venv") {
    $pythonExe = if (Test-Path ".venv\Scripts\python.exe") {
        ".\.venv\Scripts\python.exe"
    } elseif (Test-Path ".python_path") {
        (Get-Content ".python_path" -Raw).Trim()
    } else {
        Get-PythonExecutable
    }
    if (-not $pythonExe) {
        Write-Host "Python interpreter not found."
        exit 1
    }
    & $pythonExe smoke_test.py
    exit $LASTEXITCODE
}

$pythonExe = Get-PythonExecutable
if (-not $pythonExe) {
    Write-Host "Python interpreter not found."
    exit 1
}
& $pythonExe smoke_test.py

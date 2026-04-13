$ErrorActionPreference = "Stop"
. $PSScriptRoot\python_tools.ps1

if (-not (Test-Path ".venv")) {
    Write-Host "Virtual environment not found. Run .\setup.ps1 first."
    exit 1
}

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
& $pythonExe cli.py

$ErrorActionPreference = "Stop"
. $PSScriptRoot\python_tools.ps1

 $pythonExe = Get-PythonExecutable
if (-not $pythonExe) {
    Write-Host "No Python 3 interpreter found. Install Python 3.10+ first."
    exit 1
}

Set-Content -Path ".python_path" -Value $pythonExe

if (-not (Test-Path ".venv")) {
    & $pythonExe -m venv .venv
}

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment python not found."
    exit 1
}

& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Base dependency installation failed."
    exit 1
}
& $venvPython -m pip install -r requirements-optional.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Optional packages could not be installed. The app will still run with fallbacks."
}

Write-Host "Base install complete."
Write-Host "Optional embeddings/vector packages:"
Write-Host "  & $venvPython -m pip install -r requirements-optional.txt"

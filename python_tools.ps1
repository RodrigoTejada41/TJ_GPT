function Get-PythonExecutable {
    $candidates = New-Object System.Collections.Generic.List[string]

    $cmdPython = Get-Command python -ErrorAction SilentlyContinue
    if ($cmdPython) {
        $candidates.Add($cmdPython.Source)
    }

    $cmdPy = Get-Command py -ErrorAction SilentlyContinue
    if ($cmdPy) {
        $launcher = $cmdPy.Source
        $resolved = & $launcher -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) {
            $candidates.Add($resolved.Trim())
        }
    }

    $roots = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        (Join-Path $env:USERPROFILE "AppData\Local\Programs\Python"),
        (Join-Path $env:ProgramFiles "Python"),
        (Join-Path ${env:ProgramFiles(x86)} "Python"),
        $env:USERPROFILE
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $roots) {
        Get-ChildItem -Path $root -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    $candidates.Add((Join-Path $env:USERPROFILE "python.exe"))

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    return $null
}

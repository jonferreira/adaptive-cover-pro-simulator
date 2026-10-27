# Adaptive Cover Pro Simulator — launcher (Windows PowerShell)
#
# Creates a local virtualenv (".venv") on first run, installs the
# dependencies from requirements.txt, then starts the web UI at
# http://127.0.0.1:8765
#
# Usage:  powershell -ExecutionPolicy Bypass -File run.ps1
$ErrorActionPreference = "Stop"

$simDir = $PSScriptRoot
$simName = Split-Path -Leaf $simDir
$acpRoot = Split-Path -Parent $simDir

$venvPython = Join-Path $simDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    # Find a real Python 3.12+ interpreter. "py" is preferred on Windows
    # because a "python" command may be the Microsoft Store stub, and Python
    # is often installed without being added to PATH.
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += "py" }
    if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += "python" }
    $localPy = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $localPy) {
        $candidates += Get-ChildItem -Path $localPy -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName
    }
    $candidates += Get-ChildItem -Path "C:\Python*" -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName

    $systemPython = $null
    foreach ($candidate in $candidates) {
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $systemPython = $candidate; break }
    }
    if (-not $systemPython) {
        Write-Error "Python 3.12+ was not found. Install it from https://www.python.org/downloads/ and make sure 'py' or 'python' is on PATH."
        exit 1
    }

    Write-Host "Creating virtual environment in .venv ..."
    & $systemPython -m venv (Join-Path $simDir ".venv")
    if ($LASTEXITCODE -ne 0) { Write-Error "Could not create the virtual environment."; exit 1 }
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $simDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { Write-Error "Dependency installation failed."; exit 1 }
}

Write-Host "Starting Adaptive Cover Pro Simulator at http://127.0.0.1:8765"
Set-Location $acpRoot
& $venvPython -m uvicorn "$simName.server:app" --host 127.0.0.1 --port 8765

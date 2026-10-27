# Adaptive Cover Pro Simulator — launcher (Windows PowerShell)
#
# Creates a local virtualenv (".venv") on first run, installs the
# dependencies from requirements.txt, then starts the web UI at
# http://127.0.0.1:8765
#
# Usage:  powershell -ExecutionPolicy Bypass -File run.ps1
$ErrorActionPreference = "Stop"

# Find a real Python 3.12+ interpreter. The Microsoft Store "python" alias
# lives under \WindowsApps\ and hangs when executed, so it is never used.
function Get-Python312Plus {
    $candidates = New-Object System.Collections.Generic.List[string]

    # The "py" launcher is the most reliable option on Windows.
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidates.Add("py") }

    # Standard install locations (checked before PATH).
    $patterns = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python3*\python.exe"),
        (Join-Path $env:ProgramFiles "Python\Python3*\python.exe")
    )
    foreach ($pattern in $patterns) {
        Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    # Finally, "python" on PATH, but never the Store stub.
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath -and $onPath.Source -notmatch '\\WindowsApps\\') { $candidates.Add($onPath.Source) }

    foreach ($candidate in $candidates) {
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
}

$simDir = $PSScriptRoot
$simName = Split-Path -Leaf $simDir
$acpRoot = Split-Path -Parent $simDir

$venvPython = Join-Path $simDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $systemPython = Get-Python312Plus
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

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $RootDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Missing virtual environment at $RootDir\.venv. Run 'uv sync --dev' first."
}

& $PythonExe (Join-Path $RootDir "scripts\package_desktop.py")

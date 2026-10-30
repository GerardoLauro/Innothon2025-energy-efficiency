$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Creazione ambiente fallita' }
    & ./.venv/Scripts/python.exe -m pip install -r requirements-base.lock
    if ($LASTEXITCODE -ne 0) { throw 'Installazione dipendenze fallita' }
    & ./.venv/Scripts/python.exe -m pip install --no-deps .
    if ($LASTEXITCODE -ne 0) { throw 'Installazione progetto fallita' }
} finally { Pop-Location }

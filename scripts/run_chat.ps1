$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
& python (Join-Path $ProjectRoot 'run_app.py') chat @Args
exit $LASTEXITCODE

param(
    [Parameter(Mandatory=$true)] [ValidateSet('Milano','Roma','Napoli')] [string]$City,
    [double]$FlatValue = 0.25,
    [string]$Values
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Values) {
    $flat = $FlatValue.ToString('G17', [System.Globalization.CultureInfo]::InvariantCulture)
    $Values = (1..24 | ForEach-Object { $flat }) -join ','
}
& python (Join-Path $ProjectRoot 'run_app.py') prices paste --city $City --values $Values
exit $LASTEXITCODE

param(
    [ValidateSet('prepare', 'infrastructure', 'experiments', 'all')]
    [string]$Stage = 'all'
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'

Push-Location $PSScriptRoot

try {
    python run_lab.py $Stage

    if ($LASTEXITCODE -ne 0) {
        throw "Laboratory failed: $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

param(
    [ValidateSet('prepare', 'benchmark', 'analyze', 'verify', 'all')]
    [string]$Stage = 'all'
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'

Push-Location $PSScriptRoot

try {
    python -m lab $Stage

    if ($LASTEXITCODE -ne 0) {
        throw "Pipeline failed: $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

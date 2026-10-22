param(
    [switch]$Build,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

if ($Build) {
    Push-Location -LiteralPath (Join-Path $root "frontend")
    try {
        npm.cmd install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "npm build failed" }
    }
    finally {
        Pop-Location
    }
}

$frontendIndex = Join-Path $root "frontend\dist\index.html"
if (-not (Test-Path -LiteralPath $frontendIndex)) {
    Write-Host "frontend/dist/index.html not found. Run: .\run.ps1 -Build" -ForegroundColor Yellow
}

python -m uvicorn app.main:app --reload --port $Port --app-dir (Join-Path $root "backend")

[CmdletBinding()]
param(
    [ValidateSet('Live', 'Demo')]
    [string]$Mode = 'Live'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repoRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/ and run this launcher again.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'npm is required. Install Node.js LTS from https://nodejs.org/ and run this launcher again.'
}

& uv sync --locked
if ($LASTEXITCODE -ne 0) { throw 'uv sync --locked failed. Fix the Python environment and run this launcher again.' }

Push-Location (Join-Path $repoRoot 'frontend')
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Check Node.js/npm and the frontend lockfile.' }
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'npm run build failed. Fix the frontend build and run this launcher again.' }
}
finally {
    Pop-Location
}

if ($Mode -eq 'Live') {
    & uv run --locked playroom-live-local --data-dir (Join-Path $repoRoot '.playroom-live') --frontend-dist (Join-Path $repoRoot 'frontend\dist') --host 127.0.0.1 --port 8000 --setup-owner --open-browser
}
else {
    & uv run --locked playroom-demo --data-dir (Join-Path $repoRoot '.playroom-demo') --frontend-dist (Join-Path $repoRoot 'frontend\dist') --host 127.0.0.1 --port 8001 --open-browser
}
exit $LASTEXITCODE

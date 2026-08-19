$ErrorActionPreference = "Stop"

$frontendVerifyDir = Join-Path $PSScriptRoot "..\frontend\.next-verify"
$frontendTsBuildInfo = Join-Path $PSScriptRoot "..\frontend\tsconfig.tsbuildinfo"

& (Join-Path $PSScriptRoot "build-frontend.ps1")
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Push-Location (Join-Path $PSScriptRoot "..\backend")
try {
  .\.venv\Scripts\python.exe -m pytest tests -q
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
} finally {
  Pop-Location
}

if (Test-Path $frontendVerifyDir) {
  Remove-Item -LiteralPath $frontendVerifyDir -Recurse -Force -ErrorAction SilentlyContinue
}

if (Test-Path $frontendTsBuildInfo) {
  Remove-Item -LiteralPath $frontendTsBuildInfo -Force -ErrorAction SilentlyContinue
}

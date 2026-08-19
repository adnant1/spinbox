$ErrorActionPreference = "Stop"

$verifyDistDir = ".next-verify"
$frontendVerifyDir = Join-Path $PSScriptRoot "..\frontend\$verifyDistDir"

if (Test-Path $frontendVerifyDir) {
  Remove-Item -LiteralPath $frontendVerifyDir -Recurse -Force
}

$env:NEXT_DIST_DIR = $verifyDistDir
npm --prefix frontend run build
$exitCode = $LASTEXITCODE
$env:NEXT_DIST_DIR = $null
exit $exitCode

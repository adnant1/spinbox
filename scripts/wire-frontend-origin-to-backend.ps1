param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$FrontendServiceName = "spinbox",
    [Parameter(Mandatory = $true)]
    [string]$InternalApiToken
)

$ErrorActionPreference = "Stop"

function Assert-LastExitCode {
    param(
        [string]$StepName
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE."
    }
}

$describedFrontendUrl = gcloud run services describe $FrontendServiceName `
  --project $ProjectId `
  --region $Region `
  --format "value(status.url)"
Assert-LastExitCode "Frontend Cloud Run service describe"

$listedFrontendUrl = gcloud run services list `
  --project $ProjectId `
  --region $Region `
  --filter "metadata.name=$FrontendServiceName" `
  --format "value(URL)"
Assert-LastExitCode "Frontend Cloud Run service list"

$frontendOrigins = @($describedFrontendUrl, $listedFrontendUrl) |
  Where-Object { $_ } |
  Select-Object -Unique

if (-not $frontendOrigins) {
    throw "Could not resolve a URL for Cloud Run service '$FrontendServiceName'."
}

Write-Host "Redeploying backend with frontend origin(s): $($frontendOrigins -join ', ')"

& "$PSScriptRoot\deploy-backend-cloud-run.ps1" `
  -ProjectId $ProjectId `
  -Region $Region `
  -InternalApiToken $InternalApiToken `
  -CorsAllowedOrigins $frontendOrigins

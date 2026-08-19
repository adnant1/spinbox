param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$Repository = "spinbox-repo",
    [string]$ServiceName = "spinbox",
    [string]$ServiceAccountName = "spinbox-frontend-sa",
    [Parameter(Mandatory = $true)]
    [string]$BackendApiBaseUrl
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

$frontendImage = "$Region-docker.pkg.dev/$ProjectId/$Repository/frontend:latest"
$serviceAccountEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$envFile = [System.IO.Path]::GetTempFileName()
@"
NEXT_PUBLIC_API_BASE_URL: "$BackendApiBaseUrl"
"@ | Set-Content -Path $envFile -Encoding ASCII

try {
  gcloud builds submit frontend --project $ProjectId --tag $frontendImage
  Assert-LastExitCode "Cloud Build image build"

  gcloud run deploy $ServiceName `
    --project $ProjectId `
    --region $Region `
    --image $frontendImage `
    --service-account $serviceAccountEmail `
    --allow-unauthenticated `
    --env-vars-file $envFile
  Assert-LastExitCode "Cloud Run deploy"

  $serviceUrl = gcloud run services describe $ServiceName `
    --project $ProjectId `
    --region $Region `
    --format "value(status.url)"
  Assert-LastExitCode "Cloud Run service describe"

  Write-Host "Frontend deployed: $serviceUrl"
  Write-Host "Runtime service account: $serviceAccountEmail"
  Write-Host "Redeploy the backend with this frontend origin in CORS before browser testing."
}
finally {
  Remove-Item -LiteralPath $envFile -Force -ErrorAction SilentlyContinue
}

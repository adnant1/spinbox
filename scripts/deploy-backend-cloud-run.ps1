param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$Repository = "spinbox-repo",
    [string]$ServiceName = "spinbox-backend",
    [string]$BackendServiceAccount,
    [string]$SandboxImageUri,
    [string]$InternalApiToken,
    [string[]]$CorsAllowedOrigins = @()
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

if (-not $InternalApiToken) {
    throw "Provide -InternalApiToken so /internal/cleanup can stay protected in Cloud Run."
}
if (-not $BackendServiceAccount) {
    $BackendServiceAccount = "spinbox-backend-sa@$ProjectId.iam.gserviceaccount.com"
}

$backendImage = "$Region-docker.pkg.dev/$ProjectId/$Repository/backend:latest"
$runnerImage = if ($SandboxImageUri) { $SandboxImageUri } else { "$Region-docker.pkg.dev/$ProjectId/$Repository/sandbox-runner:latest" }
$corsOrigins = @("http://localhost:3000", "http://127.0.0.1:3000") + $CorsAllowedOrigins
$corsValue = ($corsOrigins | Where-Object { $_ } | Select-Object -Unique) -join ","
$envFile = [System.IO.Path]::GetTempFileName()
$runnerBuildConfig = [System.IO.Path]::GetTempFileName()
@"
GCP_PROJECT_ID: "$ProjectId"
GCP_REGION: "$Region"
ARTIFACT_REPOSITORY: "$Repository"
IMAGE_URI: "$runnerImage"
SANDBOX_TTL_SECONDS: "3600"
FIRESTORE_DATABASE_ID: "spinbox-sandboxes"
SANDBOX_REGISTRY_COLLECTION: "spinbox-sandboxes"
RUNNER_REGISTRY_COLLECTION: "spinbox-runners"
RUNNER_MAX_SANDBOXES: "10"
INTERNAL_API_TOKEN: "$InternalApiToken"
CORS_ALLOWED_ORIGINS: "$corsValue"
"@ | Set-Content -Path $envFile -Encoding ASCII

@"
steps:
- name: gcr.io/cloud-builders/docker
  args:
  - build
  - -f
  - runner.Dockerfile
  - -t
  - $runnerImage
  - .
images:
- $runnerImage
"@ | Set-Content -Path $runnerBuildConfig -Encoding ASCII

try {
  gcloud builds submit backend --project $ProjectId --tag $backendImage
  Assert-LastExitCode "Cloud Build image build"

  gcloud builds submit backend --project $ProjectId --config $runnerBuildConfig
  Assert-LastExitCode "Cloud Build runner image build"

  gcloud run deploy $ServiceName `
    --project $ProjectId `
    --region $Region `
    --image $backendImage `
    --service-account $BackendServiceAccount `
    --allow-unauthenticated `
    --env-vars-file $envFile
  Assert-LastExitCode "Cloud Run deploy"
}
finally {
  Remove-Item -LiteralPath $envFile -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $runnerBuildConfig -Force -ErrorAction SilentlyContinue
}

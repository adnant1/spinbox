param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$ServiceAccountName = "spinbox-frontend-sa",
    [string]$ServiceAccountDisplayName = "Spinbox Frontend Cloud Run"
)

$ErrorActionPreference = "Stop"

$serviceAccountEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"

$existing = gcloud iam service-accounts list `
  --project $ProjectId `
  --filter "email:$serviceAccountEmail" `
  --format "value(email)"

if (-not $existing) {
  gcloud iam service-accounts create $ServiceAccountName `
    --project $ProjectId `
    --display-name $ServiceAccountDisplayName
}

Write-Host "Frontend service account ready: $serviceAccountEmail"
Write-Host "No project roles were granted. Add only the minimum runtime roles if the frontend later calls Google Cloud APIs."

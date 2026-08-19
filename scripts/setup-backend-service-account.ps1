param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$ServiceAccountName = "spinbox-backend-sa",
    [string]$ServiceAccountDisplayName = "Spinbox Backend Cloud Run",
    [string]$Region = "us-central1"
)

$ErrorActionPreference = "Stop"

$serviceAccountEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"

gcloud services enable firestore.googleapis.com --project $ProjectId

$existing = gcloud iam service-accounts list `
  --project $ProjectId `
  --filter "email:$serviceAccountEmail" `
  --format "value(email)"

if (-not $existing) {
  gcloud iam service-accounts create $ServiceAccountName `
    --project $ProjectId `
    --display-name $ServiceAccountDisplayName
}

gcloud projects add-iam-policy-binding $ProjectId `
  --member "serviceAccount:$serviceAccountEmail" `
  --role "roles/run.admin"

gcloud projects add-iam-policy-binding $ProjectId `
  --member "serviceAccount:$serviceAccountEmail" `
  --role "roles/run.invoker"

gcloud projects add-iam-policy-binding $ProjectId `
  --member "serviceAccount:$serviceAccountEmail" `
  --role "roles/datastore.user"

Write-Host "Backend service account ready: $serviceAccountEmail"
Write-Host "This uses predefined roles/run.admin, roles/run.invoker, and roles/datastore.user."

# Mind staging infrastructure

This Terraform root establishes the reproducible Google Cloud foundation for
Mind staging: required APIs, an Artifact Registry repository, a least-privilege
Cloud Run service account with Firestore and Firebase Authentication access,
Secret Manager containers, and an optional Cloud Run
API service. Firebase Hosting assets and Firestore rules are deployed with the
Firebase CLI from the repository root.

## Bootstrap the existing staging project

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```

The existing `(default)` Firestore database was created in the Firebase console.
Leave `manage_firestore_database = false` until it is imported into Terraform:

```bash
terraform import 'google_firestore_database.default[0]' \
  'projects/mind-staging-ce427/databases/(default)'
```

Then set `manage_firestore_database = true` and verify that `terraform plan`
shows no database replacement. Never recreate the database to change location.

Before enabling Cloud Run, add secret versions without putting values in source
control:

```bash
printf '%s' "$OPENAI_API_KEY" | \
  gcloud secrets versions add mind-openai-api-key-staging --data-file=-
printf '%s' "$DEEPSEEK_API_KEY" | \
  gcloud secrets versions add mind-deepseek-api-key-staging --data-file=-
```

Build and push the API image, put its immutable digest in `api_image`, then set
`deploy_cloud_run = true`. After Terraform returns `api_url`, build the frontend
with that URL and deploy Hosting plus Firestore rules:

```bash
npm run build
firebase deploy --project mind-staging-ce427 --only hosting,firestore
```

Terraform state may contain infrastructure metadata and must use a protected
remote backend before a second operator or production environment is added.

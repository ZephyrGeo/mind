output "artifact_registry_repository" {
  value = google_artifact_registry_repository.api.name
}

output "api_service_account" {
  value = google_service_account.api.email
}

output "build_service_account" {
  value = google_service_account.build.email
}

output "api_url" {
  value = try(google_cloud_run_v2_service.api[0].uri, null)
}

locals {
  required_services = toset([
    "artifactregistry.googleapis.com",
    "firestore.googleapis.com",
    "firebase.googleapis.com",
    "iam.googleapis.com",
    "identitytoolkit.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "api" {
  project       = var.project_id
  location      = var.region
  repository_id = "mind-api"
  description   = "Immutable Mind API container images"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "api" {
  project      = var.project_id
  account_id   = "mind-api-staging"
  display_name = "Mind staging API"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "build" {
  project      = var.project_id
  account_id   = "mind-build-staging"
  display_name = "Mind staging image builder"

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "api_roles" {
  for_each = toset([
    "roles/datastore.user",
    "roles/firebaseauth.admin",
    "roles/logging.logWriter",
    "roles/secretmanager.secretAccessor",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "build_role" {
  project = var.project_id
  role    = "roles/run.builder"
  member  = "serviceAccount:${google_service_account.build.email}"
}

resource "google_storage_bucket" "files" {
  project                     = var.project_id
  name                        = var.file_storage_bucket != "" ? var.file_storage_bucket : "${var.project_id}-mind-files"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  soft_delete_policy {
    retention_duration_seconds = 0
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "api_files" {
  bucket = google_storage_bucket.files.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret" "openai" {
  project   = var.project_id
  secret_id = "mind-openai-api-key-staging"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "deepseek" {
  project   = var.project_id
  secret_id = "mind-deepseek-api-key-staging"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_firestore_database" "default" {
  count = var.manage_firestore_database ? 1 : 0

  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  deletion_policy = "ABANDON"

  depends_on = [google_project_service.required]
}

resource "google_firestore_index" "memory_embedding" {
  project     = var.project_id
  database    = "(default)"
  collection  = "memories"
  query_scope = "COLLECTION"

  fields {
    field_path = "__name__"
    order      = "ASCENDING"
  }

  fields {
    field_path = "embedding"
    vector_config {
      dimension = 256
      flat {}
    }
  }

  deletion_policy = "ABANDON"
  skip_wait       = true

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "api" {
  count = var.deploy_cloud_run ? 1 : 0

  project             = var.project_id
  name                = "mind-api-staging"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api.email
    timeout         = "900s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.api_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "MIND_ENV"
        value = var.environment
      }
      env {
        name  = "MIND_AUTH_PROVIDER"
        value = "firebase"
      }
      env {
        name  = "MIND_FIREBASE_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "MIND_ALLOWED_USER_EMAILS"
        value = var.allowed_user_emails
      }
      env {
        name  = "MIND_REQUIRE_VERIFIED_EMAIL"
        value = "1"
      }
      env {
        name  = "MIND_FIREBASE_CHECK_REVOKED"
        value = "1"
      }
      env {
        name  = "MIND_PERSISTENCE_PROVIDER"
        value = "firestore"
      }
      env {
        name  = "MIND_FIRESTORE_DATABASE_ID"
        value = "(default)"
      }
      env {
        name  = "MIND_FILE_STORAGE_PROVIDER"
        value = "gcs"
      }
      env {
        name  = "MIND_FILE_STORAGE_BUCKET"
        value = google_storage_bucket.files.name
      }
      env {
        name  = "MIND_MAX_FILE_BYTES"
        value = "20000000"
      }
      env {
        name  = "MIND_MAX_FILE_PAGES"
        value = "200"
      }
      env {
        name  = "MIND_MAX_EXTRACTED_FILE_CHARACTERS"
        value = "120000"
      }
      env {
        name  = "MIND_MAX_FILE_CONTEXT_CHARACTERS"
        value = "24000"
      }
      env {
        name  = "MIND_MAX_FILES_PER_REQUEST"
        value = "5"
      }
      env {
        name  = "MIND_CHAT_DAILY_LIMIT"
        value = "30"
      }
      env {
        name  = "MIND_RESEARCH_DAILY_LIMIT"
        value = "2"
      }
      env {
        name  = "MIND_RESEARCH_MAX_ACTIVE_PER_USER"
        value = "1"
      }

      env {
        name  = "MIND_MEMORY_RETRIEVAL_LIMIT"
        value = "5"
      }

      env {
        name  = "MIND_MEMORY_MAX_CONTEXT_CHARACTERS"
        value = "4000"
      }
      env {
        name  = "MIND_MEMORY_PROVIDER"
        value = "openai"
      }
      env {
        name  = "MIND_MEMORY_MODEL"
        value = "gpt-5.4-mini"
      }
      env {
        name  = "MIND_MEMORY_REASONING_EFFORT"
        value = "low"
      }
      env {
        name  = "MIND_MEMORY_TIMEOUT_SECONDS"
        value = "45"
      }
      env {
        name  = "MIND_EMBEDDING_PROVIDER"
        value = "openai"
      }
      env {
        name  = "MIND_EMBEDDING_MODEL"
        value = "text-embedding-3-small"
      }
      env {
        name  = "MIND_EMBEDDING_DIMENSIONS"
        value = "256"
      }
      env {
        name  = "MIND_MEMORY_SEMANTIC_THRESHOLD"
        value = "0.68"
      }
      env {
        name  = "MIND_ALLOWED_ORIGINS"
        value = var.allowed_origins
      }
      env {
        name  = "MIND_MODEL_PROVIDER"
        value = "deepseek"
      }
      env {
        name  = "MIND_RESEARCH_PROVIDER"
        value = "openai"
      }
      env {
        name  = "MIND_RESEARCH_MODEL"
        value = "gpt-5.6-terra"
      }
      env {
        name  = "MIND_RESEARCH_REASONING_EFFORT"
        value = "high"
      }
      env {
        name  = "MIND_RESEARCH_MAX_TOOL_CALLS"
        value = "12"
      }
      env {
        name  = "MIND_RESEARCH_MAX_SEARCH_ROUNDS"
        value = "2"
      }
      env {
        name  = "MIND_RESEARCH_MAX_SUBQUESTIONS"
        value = "6"
      }
      env {
        name  = "MIND_RESEARCH_MAX_TOTAL_TOOL_CALLS"
        value = "24"
      }
      env {
        name  = "MIND_RESEARCH_TOOL_CALL_OVERRUN_RATIO"
        value = "0.15"
      }
      env {
        name  = "MIND_RESEARCH_MAX_TOOL_CALL_OVERRUN"
        value = "3"
      }
      env {
        name  = "MIND_RESEARCH_MIN_CITATION_COVERAGE"
        value = "0.8"
      }
      env {
        name  = "MIND_RESEARCH_JOB_TIMEOUT_SECONDS"
        value = "600"
      }
      env {
        name  = "MIND_RESEARCH_SOFT_TIMEOUT_SECONDS"
        value = "420"
      }
      env {
        name  = "MIND_RESEARCH_MAX_CONCURRENT_SEARCHES"
        value = "2"
      }
      env {
        name  = "MIND_RESEARCH_MAX_TRANSPORT_RETRIES"
        value = "5"
      }
      env {
        name  = "MIND_RESEARCH_MAX_RATE_LIMIT_RETRIES"
        value = "3"
      }
      env {
        name  = "MIND_RESEARCH_MAX_STAGE_ATTEMPTS"
        value = "2"
      }
      env {
        name  = "MIND_RESEARCH_RETRY_BASE_SECONDS"
        value = "2"
      }
      env {
        name  = "MIND_RESEARCH_MAX_EVIDENCE_CHARACTERS"
        value = "60000"
      }
      env {
        name = "OPENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.openai.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DEEPSEEK_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.deepseek.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.api_image != ""
      error_message = "api_image is required when deploy_cloud_run is true."
    }
    precondition {
      condition     = var.allowed_origins != ""
      error_message = "allowed_origins is required for staging Cloud Run."
    }
  }

  depends_on = [
    google_project_iam_member.api_roles,
    google_secret_manager_secret.deepseek,
    google_secret_manager_secret.openai,
    google_storage_bucket_iam_member.api_files,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public_api" {
  count = var.deploy_cloud_run ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

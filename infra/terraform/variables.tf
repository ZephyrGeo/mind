variable "project_id" {
  description = "Existing Firebase/GCP staging project ID."
  type        = string
}

variable "region" {
  description = "Cloud Run and Artifact Registry region."
  type        = string
  default     = "asia-northeast1"
}

variable "environment" {
  description = "Mind runtime environment label."
  type        = string
  default     = "staging"
}

variable "allowed_user_emails" {
  description = "Comma-separated reviewer/owner allowlist."
  type        = string
  sensitive   = true
}

variable "allowed_origins" {
  description = "Comma-separated exact frontend origins."
  type        = string
  default     = ""
}

variable "api_image" {
  description = "Immutable Artifact Registry API image digest."
  type        = string
  default     = ""
}

variable "deploy_cloud_run" {
  description = "Create Cloud Run only after secrets and an image exist."
  type        = bool
  default     = false
}

variable "manage_firestore_database" {
  description = "Enable only after importing the existing database."
  type        = bool
  default     = false
}

variable "min_instances" {
  description = "Minimum Cloud Run instances; staging scales to zero."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Initial cost and capacity guardrail."
  type        = number
  default     = 2
}

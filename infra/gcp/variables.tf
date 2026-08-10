variable "project_id" {
  type = string
}
variable "region" {
  type    = string
  default = "us-east1"
}
variable "gemini_location" {
  type    = string
  default = "global"
}
variable "service_name" {
  type    = string
  default = "ttlab-advisor"
}
variable "container_image" {
  type = string
}
variable "public_base_url" {
  type = string
}
variable "public_hostname" {
  type = string
}
variable "database_name" {
  type    = string
  default = "advisor"
}
variable "database_tier" {
  type    = string
  default = "db-custom-2-7680"
}
variable "scheduler_cron" {
  type    = string
  default = "0 2 * * *"
}
variable "scheduler_timezone" {
  type    = string
  default = "America/La_Paz"
}
variable "bucket_retention_days" {
  type    = number
  default = 30
}
variable "auth_actors_json" {
  type      = string
  sensitive = true
  default   = "[]"
}
variable "cloud_build_service_account" {
  description = "Cloud Build execution service-account email; defaults to the legacy project Cloud Build account"
  type        = string
  default     = null
}

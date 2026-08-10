data "google_project" "current" {}

locals {
  services = toset([
    "aiplatform.googleapis.com", "artifactregistry.googleapis.com", "cloudbuild.googleapis.com",
    "run.googleapis.com", "sqladmin.googleapis.com", "storage.googleapis.com",
    "secretmanager.googleapis.com", "cloudscheduler.googleapis.com", "iamcredentials.googleapis.com"
  ])
  api_name = "${var.service_name}-api"
  job_name = "${var.service_name}-maintenance"
  cloud_build_service_account = coalesce(
    var.cloud_build_service_account,
    "${data.google_project.current.number}@cloudbuild.gserviceaccount.com",
  )
}

resource "google_project_service" "required" {
  for_each           = local.services
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"
  depends_on    = [google_project_service.required]
}
resource "google_artifact_registry_repository_iam_member" "cloud_build_writer" {
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${local.cloud_build_service_account}"
}

resource "google_storage_bucket" "corpus" {
  name                        = "${var.project_id}-${var.service_name}-private"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  retention_policy { retention_period = var.bucket_retention_days * 86400 }
  lifecycle_rule {
    condition { num_newer_versions = 10 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.required]
}

resource "google_service_account" "api" {
  account_id   = "${var.service_name}-api"
  display_name = "TTLAB Advisor Cloud Run API"
}
resource "google_service_account" "maintenance" {
  account_id   = "${var.service_name}-job"
  display_name = "TTLAB Advisor maintenance jobs"
}
resource "google_project_iam_member" "cloud_build_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${local.cloud_build_service_account}"
}
resource "google_service_account_iam_member" "cloud_build_uses_api" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.cloud_build_service_account}"
}
resource "google_service_account_iam_member" "cloud_build_uses_maintenance" {
  service_account_id = google_service_account.maintenance.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.cloud_build_service_account}"
}

resource "google_project_iam_member" "api_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.api.email}"
}
resource "google_project_iam_member" "api_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.api.email}"
}
resource "google_project_iam_member" "job_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.maintenance.email}"
}
resource "google_project_iam_member" "api_sql_login" {
  project = var.project_id
  role    = "roles/cloudsql.instanceUser"
  member  = "serviceAccount:${google_service_account.api.email}"
}
resource "google_project_iam_member" "job_sql_login" {
  project = var.project_id
  role    = "roles/cloudsql.instanceUser"
  member  = "serviceAccount:${google_service_account.maintenance.email}"
}
resource "google_storage_bucket_iam_member" "api_read" {
  bucket = google_storage_bucket.corpus.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.api.email}"
}
resource "google_storage_bucket_iam_member" "job_write" {
  bucket = google_storage_bucket.corpus.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.maintenance.email}"
}

resource "google_sql_database_instance" "postgres" {
  name                = "${var.service_name}-postgres"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = true
  settings {
    tier              = var.database_tier
    availability_type = "REGIONAL"
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "03:00"
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }
    ip_configuration { ipv4_enabled = true }
  }
  depends_on = [google_project_service.required]
}
resource "google_sql_database" "app" {
  name     = var.database_name
  instance = google_sql_database_instance.postgres.name
}
resource "google_sql_user" "api" {
  name     = trimsuffix(google_service_account.api.email, ".gserviceaccount.com")
  instance = google_sql_database_instance.postgres.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}
resource "google_sql_user" "maintenance" {
  name     = trimsuffix(google_service_account.maintenance.email, ".gserviceaccount.com")
  instance = google_sql_database_instance.postgres.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_secret_manager_secret" "rate_salt" {
  secret_id = "${var.service_name}-rate-limit-salt"
  replication {
    auto {}
  }
}
resource "google_secret_manager_secret" "auth_actors" {
  secret_id = "${var.service_name}-auth-actors-json"
  replication {
    auto {}
  }
}
resource "random_password" "rate_salt" {
  length  = 64
  special = false
}
resource "google_secret_manager_secret_version" "rate_salt" {
  secret      = google_secret_manager_secret.rate_salt.id
  secret_data = random_password.rate_salt.result
}
resource "google_secret_manager_secret_version" "auth_actors" {
  secret      = google_secret_manager_secret.auth_actors.id
  secret_data = var.auth_actors_json
}
resource "google_secret_manager_secret_iam_member" "api_rate_salt" {
  secret_id = google_secret_manager_secret.rate_salt.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}
resource "google_secret_manager_secret_iam_member" "api_auth" {
  secret_id = google_secret_manager_secret.auth_actors.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_cloud_run_v2_service" "api" {
  name                = local.api_name
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"
  template {
    service_account = google_service_account.api.email
    scaling {
      min_instance_count = 1
      max_instance_count = 3
    }
    containers {
      image = var.container_image
      resources {
        limits   = { cpu = "2", memory = "4Gi" }
        cpu_idle = true
      }
      ports { container_port = 8080 }
      dynamic "env" {
        for_each = {
          TTLAB_RUNTIME_PROFILE           = "gcp"
          TTLAB_DATABASE_URL              = "postgresql+pg8000://"
          TTLAB_CLOUD_SQL_INSTANCE        = google_sql_database_instance.postgres.connection_name
          TTLAB_CLOUD_SQL_DATABASE        = google_sql_database.app.name
          TTLAB_CLOUD_SQL_IAM_USER        = trimsuffix(google_service_account.api.email, ".gserviceaccount.com")
          TTLAB_GOOGLE_CLOUD_PROJECT      = var.project_id
          TTLAB_GOOGLE_CLOUD_LOCATION     = var.gemini_location
          TTLAB_STORAGE_BACKEND           = "gcs"
          TTLAB_GCS_BUCKET                = google_storage_bucket.corpus.name
          TTLAB_SECURITY_MODE             = "production"
          TTLAB_PUBLIC_BASE_URL           = var.public_base_url
          TTLAB_FRONTEND_URL              = var.public_base_url
          TTLAB_TRUSTED_HOSTS             = jsonencode([var.public_hostname])
          TTLAB_CORS_ORIGINS              = jsonencode([var.public_base_url])
          TTLAB_DEFAULT_LLM_PROVIDER      = "vertex_gemini"
          TTLAB_ALLOWED_LLM_PROVIDERS     = jsonencode(["vertex_gemini"])
          TTLAB_PUBLIC_PROVIDER_SELECTION = "false"
          TTLAB_SYNC_EXECUTION_MODE       = "disabled"
          TTLAB_API_WORKER_COUNT          = "1"
        }
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "TTLAB_RATE_LIMIT_HASH_SALT"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.rate_salt.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "TTLAB_AUTH_ACTORS_JSON"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.auth_actors.secret_id
            version = "latest"
          }
        }
      }
    }
    max_instance_request_concurrency = 8
  }
  depends_on = [
    google_sql_user.api,
    google_secret_manager_secret_iam_member.api_auth,
    google_secret_manager_secret_version.rate_salt,
    google_secret_manager_secret_version.auth_actors,
  ]
}
resource "google_cloud_run_v2_service_iam_member" "public" {
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_job" "maintenance" {
  name     = local.job_name
  location = var.region
  template {
    template {
      service_account = google_service_account.maintenance.email
      max_retries     = 1
      timeout         = "3600s"
      containers {
        image   = var.container_image
        command = ["python"]
        args    = ["-m", "app.ingestion.sync_worker", "--once", "--trigger", "scheduled"]
        dynamic "env" {
          for_each = {
            TTLAB_RUNTIME_PROFILE           = "gcp"
            TTLAB_DATABASE_URL              = "postgresql+pg8000://"
            TTLAB_CLOUD_SQL_INSTANCE        = google_sql_database_instance.postgres.connection_name
            TTLAB_CLOUD_SQL_DATABASE        = google_sql_database.app.name
            TTLAB_CLOUD_SQL_IAM_USER        = trimsuffix(google_service_account.maintenance.email, ".gserviceaccount.com")
            TTLAB_GOOGLE_CLOUD_PROJECT      = var.project_id
            TTLAB_STORAGE_BACKEND           = "gcs"
            TTLAB_GCS_BUCKET                = google_storage_bucket.corpus.name
            TTLAB_SECURITY_MODE             = "production"
            TTLAB_DEFAULT_LLM_PROVIDER      = "offline_extractive"
            TTLAB_ALLOWED_LLM_PROVIDERS     = jsonencode(["offline_extractive"])
            TTLAB_PUBLIC_PROVIDER_SELECTION = "false"
            TTLAB_RATE_LIMIT_HASH_SALT      = "maintenance-job-not-public-0000000000000000"
            TTLAB_PUBLIC_BASE_URL           = var.public_base_url
            TTLAB_TRUSTED_HOSTS             = jsonencode([var.public_hostname])
            TTLAB_CORS_ORIGINS              = jsonencode([var.public_base_url])
            TTLAB_SYNC_EXECUTION_MODE       = "offline_single_writer"
            TTLAB_SYNC_DOWNLOAD_PDFS        = "false"
            TTLAB_SERVICE_ROLE              = "offline_worker"
          }
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job" "migrate" {
  name     = "${var.service_name}-migrate"
  location = var.region
  template {
    template {
      service_account = google_service_account.maintenance.email
      max_retries     = 0
      timeout         = "1800s"
      containers {
        image   = var.container_image
        command = ["python"]
        args    = ["-m", "app.migrate"]
        dynamic "env" {
          for_each = {
            TTLAB_RUNTIME_PROFILE           = "gcp"
            TTLAB_DATABASE_URL              = "postgresql+pg8000://"
            TTLAB_CLOUD_SQL_INSTANCE        = google_sql_database_instance.postgres.connection_name
            TTLAB_CLOUD_SQL_DATABASE        = google_sql_database.app.name
            TTLAB_CLOUD_SQL_IAM_USER        = trimsuffix(google_service_account.maintenance.email, ".gserviceaccount.com")
            TTLAB_GOOGLE_CLOUD_PROJECT      = var.project_id
            TTLAB_STORAGE_BACKEND           = "gcs"
            TTLAB_GCS_BUCKET                = google_storage_bucket.corpus.name
            TTLAB_SECURITY_MODE             = "production"
            TTLAB_DEFAULT_LLM_PROVIDER      = "offline_extractive"
            TTLAB_ALLOWED_LLM_PROVIDERS     = jsonencode(["offline_extractive"])
            TTLAB_PUBLIC_PROVIDER_SELECTION = "false"
            TTLAB_RATE_LIMIT_HASH_SALT      = "migration-job-not-public-000000000000000000"
            TTLAB_PUBLIC_BASE_URL           = var.public_base_url
            TTLAB_TRUSTED_HOSTS             = jsonencode([var.public_hostname])
            TTLAB_CORS_ORIGINS              = jsonencode([var.public_base_url])
            TTLAB_SYNC_EXECUTION_MODE       = "disabled"
            TTLAB_SERVICE_ROLE              = "offline_worker"
          }
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler" {
  location = google_cloud_run_v2_job.maintenance.location
  name     = google_cloud_run_v2_job.maintenance.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.maintenance.email}"
}
resource "google_cloud_scheduler_job" "maintenance" {
  name      = "${local.job_name}-schedule"
  region    = var.region
  schedule  = var.scheduler_cron
  time_zone = var.scheduler_timezone
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.maintenance.id}:run"
    oauth_token { service_account_email = google_service_account.maintenance.email }
  }
  depends_on = [google_cloud_run_v2_job_iam_member.scheduler]
}

output "artifact_repository" { value = google_artifact_registry_repository.app.name }
output "cloud_run_service" { value = google_cloud_run_v2_service.api.name }
output "cloud_run_uri" { value = google_cloud_run_v2_service.api.uri }
output "cloud_sql_connection_name" { value = google_sql_database_instance.postgres.connection_name }
output "private_bucket" { value = google_storage_bucket.corpus.name }
output "maintenance_job" { value = google_cloud_run_v2_job.maintenance.name }
output "migration_job" { value = google_cloud_run_v2_job.migrate.name }
output "secrets_requiring_versions" {
  value = [google_secret_manager_secret.rate_salt.secret_id, google_secret_manager_secret.auth_actors.secret_id]
}

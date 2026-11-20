output "raw_bucket_url" {
  description = "The GCS URL of the raw data lake."
  value       = "gs://${google_storage_bucket.raw_data_lake.name}"
}

output "bronze_dataset_id" {
  description = "Bronze layer BigQuery dataset ID."
  value       = google_bigquery_dataset.bronze.dataset_id
}

output "silver_dataset_id" {
  description = "Silver layer BigQuery dataset ID."
  value       = google_bigquery_dataset.silver.dataset_id
}

output "gold_dataset_id" {
  description = "Gold layer BigQuery dataset ID."
  value       = google_bigquery_dataset.gold.dataset_id
}

output "pipeline_service_account_email" {
  description = "Email of the service account for automated pipeline runners."
  value       = google_service_account.pipeline_runner.email
}

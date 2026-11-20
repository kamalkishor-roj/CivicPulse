variable "project_id" {
  description = "The GCP Project ID where resources will be provisioned."
  type        = string
  default     = "civicpulse-gcp-project"
}

variable "region" {
  description = "The primary Google Cloud region for compute and storage."
  type        = string
  default     = "us-central1"
}

variable "bigquery_location" {
  description = "The regional or multi-regional location for BigQuery datasets."
  type        = string
  default     = "US"
}

variable "raw_bucket_name" {
  description = "Globally unique name for the Cloud Storage raw data lake bucket."
  type        = string
  default     = "civicpulse-chicago311-raw-lake"
}

variable "bronze_dataset_name" {
  description = "BigQuery dataset name for Bronze raw landing."
  type        = string
  default     = "civicpulse_bronze"
}

variable "silver_dataset_name" {
  description = "BigQuery dataset name for Silver cleansed entities and SCD Type 2."
  type        = string
  default     = "civicpulse_silver"
}

variable "gold_dataset_name" {
  description = "BigQuery dataset name for Gold analytics data marts."
  type        = string
  default     = "civicpulse_gold"
}

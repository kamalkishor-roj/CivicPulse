terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.20.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ==============================================================================
# 1. Google Cloud Storage (GCS) - Raw Immutable Data Lake
# ==============================================================================
resource "google_storage_bucket" "raw_data_lake" {
  name          = var.raw_bucket_name
  location      = var.bigquery_location
  storage_class = "STANDARD"

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  labels = {
    platform    = "civicpulse"
    environment = "production"
    layer       = "raw"
  }
}

# ==============================================================================
# 2. BigQuery Medallion Architecture Datasets
# ==============================================================================

# Bronze Dataset
resource "google_bigquery_dataset" "bronze" {
  dataset_id                  = var.bronze_dataset_name
  friendly_name               = "CivicPulse Bronze Layer"
  description                 = "Immutable raw landing tables with audit metadata"
  location                    = var.bigquery_location
  default_table_expiration_ms = null

  labels = {
    layer = "bronze"
  }
}

# Silver Dataset
resource "google_bigquery_dataset" "silver" {
  dataset_id    = var.silver_dataset_name
  friendly_name = "CivicPulse Silver Layer"
  description   = "Cleansed, deduplicated, and SCD Type 2 status history dimension tables"
  location      = var.bigquery_location

  labels = {
    layer = "silver"
  }
}

# Gold Dataset
resource "google_bigquery_dataset" "gold" {
  dataset_id    = var.gold_dataset_name
  friendly_name = "CivicPulse Gold Layer"
  description   = "Aggregated intelligence data marts answering operational backlog and resolution velocity"
  location      = var.bigquery_location

  labels = {
    layer = "gold"
  }
}

# ==============================================================================
# 3. BigQuery Tables & Partitioning
# ==============================================================================

# Silver Current State Table
resource "google_bigquery_table" "silver_service_requests" {
  dataset_id          = google_bigquery_dataset.silver.dataset_id
  table_id            = "silver_service_requests"
  description         = "Cleansed and deduplicated service requests current state"
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "created_date"
  }

  clustering = ["agency", "status", "ward"]

  schema = jsonencode([
    { name = "service_request_id", type = "STRING", mode = "REQUIRED", description = "Primary Key" },
    { name = "sr_type", type = "STRING", mode = "REQUIRED", description = "Complaint type" },
    { name = "sr_short_code", type = "STRING", mode = "NULLABLE" },
    { name = "agency", type = "STRING", mode = "REQUIRED" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "created_date", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "last_modified_date", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "closed_date", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "resolution_time_hours", type = "FLOAT", mode = "NULLABLE" },
    { name = "street_address", type = "STRING", mode = "NULLABLE" },
    { name = "zip_code", type = "STRING", mode = "NULLABLE" },
    { name = "ward", type = "INTEGER", mode = "NULLABLE" },
    { name = "community_area", type = "INTEGER", mode = "NULLABLE" },
    { name = "police_district", type = "INTEGER", mode = "NULLABLE" },
    { name = "latitude", type = "FLOAT", mode = "NULLABLE" },
    { name = "longitude", type = "FLOAT", mode = "NULLABLE" },
    { name = "is_duplicate", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "is_reopened", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "record_hash", type = "STRING", mode = "REQUIRED" },
    { name = "extended_attributes", type = "JSON", mode = "NULLABLE" },
    { name = "updated_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}

# Silver SCD Type 2 Dimension Table
resource "google_bigquery_table" "dim_status_history" {
  dataset_id          = google_bigquery_dataset.silver.dataset_id
  table_id            = "dim_service_request_status_history"
  description         = "SCD Type 2 status transition intervals"
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "effective_start_date"
  }

  clustering = ["service_request_id", "status", "is_current"]

  schema = jsonencode([
    { name = "status_history_sk", type = "STRING", mode = "REQUIRED", description = "Surrogate Key" },
    { name = "service_request_id", type = "STRING", mode = "REQUIRED" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "effective_start_date", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "effective_end_date", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "is_current", type = "BOOLEAN", mode = "REQUIRED" },
    { name = "version", type = "INTEGER", mode = "REQUIRED" },
    { name = "duration_in_status_hours", type = "FLOAT", mode = "NULLABLE" },
    { name = "status_sequence_order", type = "INTEGER", mode = "REQUIRED" },
    { name = "created_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}

# ==============================================================================
# 4. IAM & Pipeline Service Account
# ==============================================================================
resource "google_service_account" "pipeline_runner" {
  account_id   = "civicpulse-pipeline-sa"
  display_name = "CivicPulse Automated Data Pipeline Service Account"
}

resource "google_project_iam_member" "gcs_access" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.pipeline_runner.email}"
}

resource "google_project_iam_member" "bq_access" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.pipeline_runner.email}"
}

resource "google_project_iam_member" "bq_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.pipeline_runner.email}"
}

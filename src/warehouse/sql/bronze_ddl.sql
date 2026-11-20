-- =====================================================================
-- CivicPulse Medallion Architecture: Bronze Layer
-- Dataset: civicpulse_bronze
-- Partitioned by ingestion date; clustered by service_request_id, sr_type
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS `@project_id.@bronze_dataset`
OPTIONS (
  location = '@location',
  description = 'Bronze raw landing layer for Chicago 311 Service Requests'
);

CREATE TABLE IF NOT EXISTS `@project_id.@bronze_dataset.bronze_service_requests`
(
  raw_payload STRING OPTIONS(description="Complete raw JSON payload from Socrata/Open311 API"),
  service_request_id STRING OPTIONS(description="Unique service request identifier"),
  sr_type STRING OPTIONS(description="Type of municipal infrastructure complaint"),
  status STRING OPTIONS(description="Operational status reported by agency"),
  created_date TIMESTAMP OPTIONS(description="Citizen submission timestamp"),
  last_modified_date TIMESTAMP OPTIONS(description="Latest update timestamp"),
  closed_date TIMESTAMP OPTIONS(description="Closure timestamp"),
  owner_department STRING OPTIONS(description="Responsible municipal agency"),
  street_address STRING OPTIONS(description="Incident street address"),
  zip_code STRING OPTIONS(description="Postal zip code"),
  ward INT64 OPTIONS(description="Chicago City Council ward (1-50)"),
  latitude FLOAT64 OPTIONS(description="Geographic latitude"),
  longitude FLOAT64 OPTIONS(description="Geographic longitude"),
  _ingested_at TIMESTAMP OPTIONS(description="Pipeline ingestion timestamp"),
  _source_batch_id STRING OPTIONS(description="UUID of ingestion batch")
)
PARTITION BY DATE(_ingested_at)
CLUSTER BY service_request_id, sr_type
OPTIONS (
  require_partition_filter = FALSE,
  description = "Append-only immutable Bronze layer"
);

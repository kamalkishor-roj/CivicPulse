-- =====================================================================
-- CivicPulse Medallion Architecture: Silver Layer
-- Dataset: civicpulse_silver
-- Current state fact table + SCD Type 2 status history dimension
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS `@project_id.@silver_dataset`
OPTIONS (
  location = '@location',
  description = 'Silver cleansed, validated, deduplicated layer'
);

-- Silver Current State Table
CREATE TABLE IF NOT EXISTS `@project_id.@silver_dataset.silver_service_requests`
(
  service_request_id STRING NOT NULL OPTIONS(description="Primary Key: Service Request ID"),
  sr_type STRING NOT NULL OPTIONS(description="Complaint type"),
  sr_short_code STRING OPTIONS(description="Standard abbreviation code (e.g., PHF, WIB)"),
  agency STRING NOT NULL OPTIONS(description="Standardized department name"),
  status STRING NOT NULL OPTIONS(description="Current status (Open, In Progress, Completed, etc.)"),
  created_date TIMESTAMP NOT NULL OPTIONS(description="Original creation timestamp"),
  last_modified_date TIMESTAMP NOT NULL OPTIONS(description="Latest modification timestamp"),
  closed_date TIMESTAMP OPTIONS(description="Resolution timestamp"),
  resolution_time_hours FLOAT64 OPTIONS(description="Resolution duration in hours"),
  street_address STRING OPTIONS(description="Standardized street address"),
  zip_code STRING OPTIONS(description="Postal code"),
  ward INT64 OPTIONS(description="Ward number"),
  community_area INT64 OPTIONS(description="Community area number (1-77)"),
  police_district INT64 OPTIONS(description="Chicago Police Department district"),
  latitude FLOAT64 OPTIONS(description="Validated latitude"),
  longitude FLOAT64 OPTIONS(description="Validated longitude"),
  is_duplicate BOOLEAN OPTIONS(description="Flag indicating duplicate complaint"),
  is_reopened BOOLEAN OPTIONS(description="Flag indicating whether complaint was reopened after completion"),
  record_hash STRING NOT NULL OPTIONS(description="SHA-256 fingerprint of mutable fields"),
  extended_attributes JSON OPTIONS(description="Dynamic extra fields supporting schema evolution"),
  updated_at TIMESTAMP NOT NULL OPTIONS(description="Warehouse pipeline update timestamp")
)
PARTITION BY DATE(created_date)
CLUSTER BY agency, status, ward
OPTIONS (
  description = "Cleansed current state of service requests"
);

-- SCD Type 2 Status History Dimension Table
CREATE TABLE IF NOT EXISTS `@project_id.@silver_dataset.dim_service_request_status_history`
(
  status_history_sk STRING NOT NULL OPTIONS(description="Surrogate Key: MD5(service_request_id + status + start_date)"),
  service_request_id STRING NOT NULL OPTIONS(description="Natural Key: Service Request ID"),
  status STRING NOT NULL OPTIONS(description="Historical status value"),
  effective_start_date TIMESTAMP NOT NULL OPTIONS(description="Interval start timestamp"),
  effective_end_date TIMESTAMP OPTIONS(description="Interval end timestamp (NULL if current)"),
  is_current BOOLEAN NOT NULL OPTIONS(description="TRUE if current active status; FALSE if historical"),
  version INT64 NOT NULL OPTIONS(description="Sequential version number for this incident"),
  duration_in_status_hours FLOAT64 OPTIONS(description="Hours spent in this specific status interval"),
  status_sequence_order INT64 NOT NULL OPTIONS(description="Ordinal position in lifecycle"),
  created_at TIMESTAMP NOT NULL OPTIONS(description="Row insertion timestamp")
)
PARTITION BY DATE(effective_start_date)
CLUSTER BY service_request_id, status, is_current
OPTIONS (
  description = "SCD Type 2 tracking status transitions across incident lifecycle"
);

-- =====================================================================
-- CivicPulse Medallion Architecture: Gold Layer Views
-- Dataset: civicpulse_gold
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS `@project_id.@gold_dataset`
OPTIONS (
  location = '@location',
  description = 'Gold aggregated data marts answering public infrastructure intelligence queries'
);

-- Mart 1: Average, Median, and P90 Resolution Time by Complaint Category
CREATE OR REPLACE VIEW `@project_id.@gold_dataset.view_resolution_time_by_category` AS
SELECT
  sr_type,
  COUNT(1) AS total_requests,
  COUNT(closed_date) AS resolved_requests,
  ROUND(AVG(resolution_time_hours), 2) AS avg_resolution_hours,
  ROUND(PERCENTILE_CONT(resolution_time_hours, 0.50) OVER(PARTITION BY sr_type), 2) AS median_resolution_hours,
  ROUND(PERCENTILE_CONT(resolution_time_hours, 0.90) OVER(PARTITION BY sr_type), 2) AS p90_resolution_hours,
  ROUND(MIN(resolution_time_hours), 2) AS min_resolution_hours,
  ROUND(MAX(resolution_time_hours), 2) AS max_resolution_hours
FROM `@project_id.@silver_dataset.silver_service_requests`
WHERE closed_date IS NOT NULL;

-- Mart 2: Agency Backlog and Ageing Profile
CREATE OR REPLACE VIEW `@project_id.@gold_dataset.view_agency_backlog` AS
SELECT
  agency,
  COUNT(1) AS total_backlog,
  COUNTIF(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_date, DAY) < 7) AS backlog_under_7_days,
  COUNTIF(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_date, DAY) BETWEEN 7 AND 30) AS backlog_7_to_30_days,
  COUNTIF(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_date, DAY) BETWEEN 31 AND 90) AS backlog_31_to_90_days,
  COUNTIF(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_date, DAY) > 90) AS backlog_over_90_days,
  ROUND(AVG(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_date, DAY)), 1) AS avg_backlog_age_days
FROM `@project_id.@silver_dataset.silver_service_requests`
WHERE status NOT IN ('Completed', 'Closed', 'Cancelled')
GROUP BY agency;

-- Mart 3: Geographic Hotspots (Wards and Zip Codes with Recurring Issues)
CREATE OR REPLACE VIEW `@project_id.@gold_dataset.view_geographic_hotspots` AS
SELECT
  ward,
  zip_code,
  sr_type,
  COUNT(1) AS complaint_count,
  COUNTIF(is_reopened) AS reopened_count,
  ROUND(AVG(resolution_time_hours), 2) AS avg_resolution_hours
FROM `@project_id.@silver_dataset.silver_service_requests`
WHERE ward IS NOT NULL
GROUP BY ward, zip_code, sr_type;

-- Mart 4: Complaint Types Taking Longest to Resolve (Top Bottlenecks)
CREATE OR REPLACE VIEW `@project_id.@gold_dataset.view_longest_resolving_complaints` AS
SELECT
  service_request_id,
  sr_type,
  agency,
  ward,
  street_address,
  created_date,
  closed_date,
  resolution_time_hours,
  is_reopened
FROM `@project_id.@silver_dataset.silver_service_requests`
WHERE resolution_time_hours IS NOT NULL
ORDER BY resolution_time_hours DESC;

-- Mart 5: Percentage of Complaints Reopened
CREATE OR REPLACE VIEW `@project_id.@gold_dataset.view_reopened_analysis` AS
SELECT
  agency,
  sr_type,
  COUNT(1) AS total_complaints,
  COUNTIF(is_reopened) AS reopened_count,
  ROUND(100.0 * COUNTIF(is_reopened) / COUNT(1), 2) AS reopen_percentage
FROM `@project_id.@silver_dataset.silver_service_requests`
GROUP BY agency, sr_type;

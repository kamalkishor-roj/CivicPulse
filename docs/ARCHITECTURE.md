# CivicPulse: Architecture & Technical Specification

CivicPulse is an enterprise-grade Public Infrastructure Intelligence Platform designed on Google Cloud Platform (GCP) and local hybrid execution engines to collect, track, and analyze the operational lifecycle of Chicago 311 municipal service requests.

---

## 1. High-Level Architecture Diagram

```
+---------------------------------------------------------------------------------------------------+
|                                      DATA INGESTION LAYER                                         |
+---------------------------------------------------------------------------------------------------+
|  Chicago Data Portal / Socrata Open311 API (Dataset: v6vf-nfxy)                                   |
|                               |                                                                   |
|                      [Incremental Polling]                                                        |
|                               v                                                                   |
|  Python Ingestion Client (APIPaginator + Rate Limiter + Watermark State Manager)                  |
|  - Exponential Backoff + Jitter on HTTP 429/5xx                                                   |
|  - Where Clause: last_modified_date > $watermark ORDER BY last_modified_date ASC                  |
+---------------------------------------------------------------------------------------------------+
                                |
                                | Atomic Write Envelope
                                v
+---------------------------------------------------------------------------------------------------+
|                                      RAW STORAGE LAYER                                            |
+---------------------------------------------------------------------------------------------------+
|  Google Cloud Storage (GCS) or Local Filesystem Staging                                           |
|  - Immutable JSON Snapshots: raw/year=YYYY/month=MM/day=DD/batch_{timestamp}_{batch_id}.json      |
|  - Storage Lifecycle Policies (Standard -> Nearline 90d -> Coldline 365d)                        |
|  - State Checkpoint: state/watermark_state.json (Watermark committed ONLY after raw write)        |
+---------------------------------------------------------------------------------------------------+
                                |
                                | Batch Extraction
                                v
+---------------------------------------------------------------------------------------------------+
|                               TRANSFORMATION ENGINE (PySpark / DuckDB)                            |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|     +-------------------------+                 +-----------------------------------------+       |
|     |   DATA QUALITY FIREWALL | --(Violations)->| Dead-Letter Queue (DLQ) Quarantine      |       |
|     |   - Primary Key Check   |                 | quarantine/year=YYYY/month=MM/day=DD/   |       |
|     |   - Temporal Paradox    |                 +-----------------------------------------+       |
|     |   - Chicago Geo Bounds  |                                                                   |
|     +-------------------------+                                                                   |
|                  |                                                                                |
|                  | (Valid Cleaned Stream)                                                         |
|                  v                                                                                |
|     +-----------------------------------------------------------------------------------+         |
|     | DEDUPLICATION & CHANGE DETECTION                                                  |         |
|     | - SHA-256 Record Fingerprinting (record_hash) across mutable business fields      |         |
|     | - Status Mutation & Reopened Complaint Detection (Completed -> Open)              |         |
|     +-----------------------------------------------------------------------------------+         |
|                  |                                                                                |
|                  v                                                                                |
|     +-----------------------------------------------------------------------------------+         |
|     | SCD TYPE 2 STATUS HISTORY ENGINE                                                  |         |
|     | - Generates chronological intervals (effective_start_date, effective_end_date)   |         |
|     | - Versioning (v1, v2, v3...) & duration_in_status_hours calculation               |         |
|     | - Resequences out-of-order & late-arriving status events                          |         |
|     +-----------------------------------------------------------------------------------+         |
+---------------------------------------------------------------------------------------------------+
                                |
                                | Medallion Ingestion
                                v
+---------------------------------------------------------------------------------------------------+
|                            DATA WAREHOUSE LAYER (BigQuery / Lakehouse)                            |
+---------------------------------------------------------------------------------------------------+
|  BRONZE LAYER (bronze_service_requests):                                                          |
|  - Partitioned by ingestion date, clustered by service_request_id. Raw audit schema.             |
|                                                                                                   |
|  SILVER LAYER:                                                                                    |
|  - silver_service_requests: Cleansed deduplicated current state with extended_attributes JSON     |
|  - dim_service_request_status_history: SCD Type 2 historical status intervals                     |
|                                                                                                   |
|  GOLD LAYER (Analytics Marts & Views):                                                            |
|  - gold_resolution_time_by_category: Avg, Median, P90 resolution hours                             |
|  - gold_agency_backlog: Backlog ageing distribution (<7d, 7-30d, 31-90d, >90d)                   |
|  - gold_geographic_hotspots: Recurring failure clusters by Ward and Zip Code                      |
|  - gold_longest_resolving_complaints: Extreme operational bottlenecks                             |
|  - gold_reopened_analysis: Complaint recidivism percentages by agency                             |
+---------------------------------------------------------------------------------------------------+
                                |
                                v
+---------------------------------------------------------------------------------------------------+
|                                PRESENTATION & SERVING LAYER                                       |
+---------------------------------------------------------------------------------------------------+
|  CivicPulse Streamlit Executive Intelligence Platform (Port 8501)                                 |
|  - Live Operational KPI Scorecards                                                                |
|  - Interactive SCD Type 2 Journey Visualizer (Day 1: Open -> Day 2: In Progress -> Day 5: Done)   |
|  - Geospatial Carto Map of Infrastructure Breakdowns across Chicago                              |
|  - Data Quality Quarantine Inspector                                                              |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Medallion Layer Schema Design

### Bronze: `bronze_service_requests`
- `raw_payload`: STRING (Full JSON payload from SODA API)
- `service_request_id`: STRING
- `sr_type`: STRING
- `status`: STRING
- `created_date`: TIMESTAMP
- `last_modified_date`: TIMESTAMP
- `closed_date`: TIMESTAMP
- `owner_department`: STRING
- `street_address`: STRING
- `zip_code`: STRING
- `ward`: INT64
- `latitude`: FLOAT64
- `longitude`: FLOAT64
- `_ingested_at`: TIMESTAMP (Partition key)
- `_source_batch_id`: STRING (Clustering key)

### Silver: `silver_service_requests`
- `service_request_id`: STRING (PK)
- `sr_type`: STRING
- `sr_short_code`: STRING
- `agency`: STRING
- `status`: STRING
- `created_date`: TIMESTAMP (Partition key)
- `last_modified_date`: TIMESTAMP
- `closed_date`: TIMESTAMP
- `resolution_time_hours`: FLOAT64
- `street_address`: STRING
- `zip_code`: STRING
- `ward`: INT64
- `community_area`: INT64
- `police_district`: INT64
- `latitude`: FLOAT64
- `longitude`: FLOAT64
- `is_duplicate`: BOOLEAN
- `is_reopened`: BOOLEAN
- `record_hash`: STRING (SHA-256 fingerprint)
- `extended_attributes`: JSON (Schema Evolution container)
- `updated_at`: TIMESTAMP

### Silver: `dim_service_request_status_history` (SCD Type 2)
- `status_history_sk`: STRING (PK: MD5(service_request_id + status + start_date))
- `service_request_id`: STRING (Natural Key)
- `status`: STRING
- `effective_start_date`: TIMESTAMP (Partition key)
- `effective_end_date`: TIMESTAMP (NULL if current active)
- `is_current`: BOOLEAN (True if active)
- `version`: INT64 (1, 2, 3...)
- `duration_in_status_hours`: FLOAT64
- `status_sequence_order`: INT64
- `created_at`: TIMESTAMP

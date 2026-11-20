# 🏙️ CivicPulse: Public Infrastructure Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![PySpark](https://img.shields.io/badge/PySpark-4.x-orange.svg)](https://spark.apache.org/)
[![GCP BigQuery](https://img.shields.io/badge/Google%20Cloud-BigQuery%20%7C%20GCS-4285F4.svg)](https://cloud.google.com/bigquery)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.2+-FFF000.svg)](https://duckdb.org/)
[![React](https://img.shields.io/badge/Frontend-React%2018%20%7C%20JavaScript-61DAFB.svg)](https://react.dev/)
[![Leaflet](https://img.shields.io/badge/Maps-Leaflet%20(No%20API%20Key)-199900.svg)](https://leafletjs.com/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC.svg)](https://www.terraform.io/)
[![Tests](https://img.shields.io/badge/Tests-16%20Passed%20(100%25)-brightgreen.svg)]()

> **An enterprise-grade Data Lakehouse and Analytics Platform built on Google Cloud Platform (GCP) and hybrid execution engines (PySpark & DuckDB) to collect, process, and analyze the full operational lifecycle of municipal 311 service requests.**

---

## 📌 Executive Summary

City governments receive tens of thousands of citizen complaints each month:
- **Road potholes** (`CDOT`)
- **Garbage collection & overflowing carts** (`Streets and Sanitation`)
- **Water supply issues & basement flooding** (`Department of Water Management`)
- **Streetlight outages** (`CDOT`)
- **Drainage & clogged catch basins** (`DWM`)
- **Illegal fly dumping** (`Streets and Sanitation`)

Instead of merely displaying total counts, **CivicPulse** collects raw operational data from the **Chicago Data Portal / Open311 API** and tracks each complaint's entire temporal lifecycle—from creation to field crew assignment, completion, and potential citizen reopening—enabling city commissioners to monitor resolution velocity, track agency backlogs, identify failure hotspots, and catch SLA breaches.

---

## 🏗️ System Architecture

![CivicPulse Architecture](docs/images/civicpulse_architecture.svg)

```
                                  CIVICPULSE DATA PLATFORM
+-----------------------------------------------------------------------------------------------+
| INGESTION LAYER (Python)                                                                      |
| - Chicago Open311 / Socrata API Connector (Dataset: v6vf-nfxy)                                 |
| - Watermark-based Incremental Extraction: $where=last_modified_date > $watermark               |
| - API Pagination ($limit, $offset) with Adaptive Rate Limiting & Exponential Backoff           |
| - Atomic Checkpoint State Manager (watermark_state.json): Zero record loss on crash           |
+-----------------------------------------------------------------------------------------------+
                                               |
                                               v
+-----------------------------------------------------------------------------------------------+
| RAW STORAGE (GCS / Local Data Lake)                                                           |
| - Immutable partitioned JSON snapshots: raw/year=YYYY/month=MM/day=DD/batch_*.json            |
| - Cloud Storage lifecycle rules: Standard -> Nearline (90d) -> Coldline (365d)                |
+-----------------------------------------------------------------------------------------------+
                                               |
                                               v
+-----------------------------------------------------------------------------------------------+
| TRANSFORMATION ENGINE (PySpark 4.x / DuckDB)                                                  |
| 1. Data Quality Firewall: Chicago geo bounding box, temporal consistency, identity checks     |
| 2. Dead-Letter Queue (DLQ): Auto-quarantining invalid records with failure codes              |
| 3. Change Detection: SHA-256 fingerprinting (record_hash) across mutable business fields     |
| 4. Deduplication: Windowing over service_request_id and last_modified_date                    |
| 5. SCD Type 2 Engine: Generates status history dimension with durations and versioning        |
| 6. Late-Arriving Data Handling: Resequences out-of-order events chronologically               |
+-----------------------------------------------------------------------------------------------+
                                               |
                                               v
+-----------------------------------------------------------------------------------------------+
| WAREHOUSE LAYER (BigQuery Medallion Architecture)                                             |
| - BRONZE: bronze_service_requests (Partitioned by ingestion date, clustered by request ID)     |
| - SILVER: silver_service_requests (Cleansed current state, extended_attributes JSON)           |
| - SILVER SCD2: dim_service_request_status_history (Chronological status intervals)            |
| - GOLD MARTS:                                                                                 |
|   * gold_resolution_time_by_category (Avg, median, p90 resolution hours)                       |
|   * gold_agency_backlog (Unresolved backlog by ageing brackets: <7d, 7-30d, 31-90d, >90d)     |
|   * gold_geographic_hotspots (Recurring failure densities by Ward & Zip Code)                 |
|   * gold_longest_resolving_complaints (Extreme bottleneck cases)                              |
|   * gold_reopened_analysis (Complaint recidivism rates by agency)                             |
+-----------------------------------------------------------------------------------------------+
                                               |
                                               v
+-----------------------------------------------------------------------------------------------+
| PRESENTATION LAYER (React & JavaScript Executive Dashboard)                                   |
| - Interactive Chicago Leaflet Map (OpenStreetMap - ZERO API KEY REQUIRED)                      |
| - Interactive SCD Type 2 Journey Visualizer (Day 1: Open -> Day 2: In Progress -> Day 5: Done)|
| - Real-time KPI Scorecards (Backlog, Avg Hours, Reopened Rate)                                |
| - Data Quality Quarantine Inspector & Pipeline Health Monitor                                 |
+-----------------------------------------------------------------------------------------------+
```

---

## 🖥️ React Executive Dashboard Preview

![CivicPulse Dashboard Preview](docs/images/dashboard_preview.svg)

---

## ⚡ Technical Features Matrix (Interview Highlights)

| Technical Feature | Implementation & Engineering Mechanism |
| :--- | :--- |
| **API Pagination** | Offset and cursor pagination (`$limit`, `$offset`) yielding clean batches across large API results. |
| **Watermarking** | Incremental extraction based on `last_modified_date > watermark ORDER BY last_modified_date ASC`. |
| **Pipeline Recovery** | State file committed **only after** durable raw landing. Failed runs leave watermark unadvanced for zero record loss. |
| **SCD Type 2 (Status History)** | Maintains complete chronological lifecycle (`effective_start_date`, `effective_end_date`, `is_current`, `version`, `duration_in_status_hours`). |
| **Late-Arriving Data** | Out-of-order event streams are re-sorted chronologically to rebuild valid interval boundaries without clobbering new states. |
| **Change Detection** | Deterministic SHA-256 fingerprint (`record_hash`) across mutable attributes; detects status shifts, reassignments, and reopenings. |
| **Deduplication** | Spark / SQL windowing: `ROW_NUMBER() OVER(PARTITION BY service_request_id ORDER BY last_modified_date DESC)`. |
| **Data Quality & Quarantine** | Multi-rule validation engine routing invalid records (temporal paradoxes, out-of-bounds coords) to a Dead-Letter Queue (DLQ). |
| **Schema Evolution** | Core fields strictly typed; unknown/newly introduced attributes captured dynamically in `extended_attributes JSON`. |
| **Historical Backfilling** | Bounded window extraction (`start_date` to `end_date`) that leaves the forward-moving production watermark untouched. |
| **Zero-API-Key Mapping** | Interactive Chicago map powered by **Leaflet.js & OpenStreetMap**; renders live geocoded markers without proprietary Mapbox tokens. |

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- Python 3.10+ (or Anaconda)
- Git

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/kamalkishor-roj/CivicPulse.git
cd CivicPulse

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the End-to-End Pipeline
```bash
# On Windows (PowerShell):
.\run.ps1 run --mode mock --max-records 400 --engine duckdb

# Or on Windows (Command Prompt):
run.bat run --mode mock --max-records 400 --engine duckdb

# Or directly with Python:
python src/pipeline.py run --mode mock --max-records 400 --engine duckdb

# Check pipeline watermark state:
.\run.ps1 status
```

### 4. Launch the React & JavaScript Intelligence Dashboard
```bash
# In PowerShell:
.\start_dashboard.ps1

# Or in Command Prompt:
start_dashboard.bat
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.
- **Pure React + JavaScript**: Modern executive design with live filtering.
- **Leaflet & OpenStreetMap**: 100% visible interactive Chicago map with **ZERO API keys or tokens required**.
- **Interactive SCD Type 2 Journey**: Visual step-by-step incident lifecycle explorer.

### 5. Run the Test Suite
```bash
pytest tests/ -v
```
All 16 unit and integration tests validate watermarking, failure recovery, data quality rules, SCD Type 2 timelines, and late-arriving updates.

---

## 🐳 Docker Deployment

Run the complete pipeline and dashboard with a single command:
```bash
docker-compose up --build
```
- **Dashboard**: Accessible at `http://localhost:8000`
- **Data Persistence**: Automatically mapped to `./data`

---

## ☁️ Google Cloud Platform Deployment (Terraform)

Provision the complete GCP infrastructure (Cloud Storage bucket, BigQuery datasets, partitioned tables, and IAM service accounts):

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your GCP project ID

terraform init
terraform plan
terraform apply
```

Then switch storage and BigQuery mode in `.env`:
```env
STORAGE_BACKEND=gcs
GCS_RAW_BUCKET=civicpulse-chicago311-raw-lake-prod
GCP_PROJECT_ID=my-gcp-infrastructure-project
```

---

## 📊 Business Intelligence & Key Insights

1. **Resolution Time by Complaint Type:**
   - Water main breaks and streetlights-all-out have strict SLA targets (<48h), while abandoned vehicles and tree debris show long-tail resolution profiles (7–14 days).
2. **Agency Backlog by Ageing Bracket:**
   - Visualizes open work orders segmented into `<7d`, `7–30d`, `31–90d`, and `>90d` buckets to spotlight chronic operational backlogs.
3. **Geographic Hotspots:**
   - Identifies specific city wards with recurring infrastructure breakdowns, directing preventive maintenance crews before citizen complaints escalate.
4. **SCD Type 2 Lifecycle Visualizer:**
   - Allows users to select any individual incident ID to view its complete operational journey:
<img width="452" height="53" alt="image" src="https://github.com/user-attachments/assets/82db06d5-3f64-4973-aeec-feac4949d2d1" />

5. **Reopened Complaint Analysis:**
   - Tracks premature closures where tickets were closed by municipal crews but subsequently reopened by citizens.

---

## 📖 Deep-Dive Documentation

- [Detailed Architecture Specification](docs/ARCHITECTURE.md)
- [Technical Interview Talking Points Guide](docs/INTERVIEW_GUIDE.md)

---

## ⚖️ License
MIT License. Built for city governments, public infrastructure teams, and modern data engineering portfolios.

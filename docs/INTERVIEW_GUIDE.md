# CivicPulse: Technical Interview Talking Points & Deep-Dive Guide

This guide prepares you to speak confidently and authoritatively about the architectural choices, distributed processing patterns, and resilience mechanisms implemented in **CivicPulse**.

---

## 1. Watermark-Based Incremental Extraction & Crash Recovery

### **Interview Talking Point:**
> *"Explain how you implemented watermark-based incremental extraction and how you prevented a failed ingestion run from losing records."*

### **The Architecture Solution:**
1. **The High-Water Mark (`last_modified_date`):**
   - We query the Chicago Socrata Open Data API using SODA query parameters:
     ```
     $where = last_modified_date > '{current_watermark}'
     $order = last_modified_date ASC
     $limit = 2000
     ```
   - Ordering by `last_modified_date ASC` is critical: it guarantees that records arrive in chronological update order, allowing deterministic batch progression.

2. **Preventing Data Loss on Failure (Two-Phase Commit Analogy):**
   - **The Problem:** If an extraction job advances the watermark in memory before the data is safely persisted to Google Cloud Storage (GCS) or disk, a crash (e.g., container OOM, network drop) would cause those extracted records to be skipped forever on the next run.
   - **The Implementation:**
     - The pipeline loads the state file (`watermark_state.json`) containing `last_extracted_watermark`.
     - When a run begins, it marks `status = "IN_PROGRESS"` with a unique `batch_id`.
     - The incoming API page is written to immutable raw storage (`raw/year=YYYY/month=MM/day=DD/batch_{id}.json`).
     - **Only after the raw write succeeds** does the `StateManager` atomically commit the new high watermark (`status = "SUCCESS"`).
     - If an error occurs at any point during fetch or write, `record_failure()` is triggered: the watermark is **never advanced**.
     - On restart, the pipeline reads the previous unadvanced watermark and fetches the exact same interval.

3. **Idempotence & Deduplication:**
   - Because ingestion is at-least-once, downstream processing in Silver deduplicates using window functions:
     ```sql
     ROW_NUMBER() OVER(PARTITION BY service_request_id ORDER BY last_modified_date DESC)
     ```
   - This ensures that re-extracting overlapping records during recovery produces zero duplicate rows in Silver.

---

## 2. SCD Type 2 (Slowly Changing Dimension Type 2) Status History

### **Interview Talking Point:**
> *"Why did you implement SCD Type 2 for incident status instead of just storing the current status?"*

### **The Business & Engineering Value:**
- **Business Need:** A city government cannot understand crew productivity or citizen satisfaction by looking only at whether a ticket is currently 'Closed'. For instance:
  - Incident 101: Open (Day 1) -> In Progress (Day 2) -> Completed (Day 5).
  - Just having "Completed" loses the critical fact that it sat in "Open" for 24 hours and took 72 hours of active crew work.
- **Implementation Mechanism:**
  - We model `dim_service_request_status_history`:
    - `status_history_sk`: Surrogate Key `MD5(service_request_id + status + effective_start_date)`
    - `service_request_id`: Incident natural key
    - `status`: Historical status value
    - `effective_start_date`: Timestamp status was entered
    - `effective_end_date`: Timestamp status was superseded (NULL for current)
    - `is_current`: Boolean flag (`TRUE` for active state, `FALSE` for closed intervals)
    - `version`: Version integer (v1, v2, v3...)
    - `duration_in_status_hours`: Computed difference in hours

### **How Late-Arriving & Out-of-Order Data is Handled:**
- In distributed environments and mobile worker systems, status updates often arrive out of order (e.g., Day 5 Completed arrives before Day 2 In Progress syncs from an offline crew tablet).
- **The Solution:** Our `SCDType2Processor` collects all known snapshots for an incident and sorts them strictly by `last_modified_date ASC`. It then evaluates:
  ```python
  effective_end_date = lead(effective_start_date).over(Window.partitionBy("service_request_id").orderBy("modified_dt"))
  ```
- This dynamically reconstructs the true operational sequence, recalculates `duration_in_status_hours`, and guarantees that only the genuinely latest chronological record holds `is_current = TRUE`.

---

## 3. Handling Reopened Complaints (Recidivism)

### **Interview Talking Point:**
> *"How do you detect and model complaints that are reopened?"*

### **The Technical Implementation:**
- A reopened ticket occurs when an incident previously recorded with status `Completed` or `Closed` receives a subsequent update with status `Open` or `In Progress`.
- **In Change Detection:** The `ChangeDetector` compares the incoming status against the previous known state. If `prev_status in ['completed', 'closed']` and `new_status in ['open', 'in progress']`, it flags `is_reopened = TRUE`.
- **In SCD Type 2:** Rather than overwriting the previous Completed interval, the engine closes the Completed state at `t_reopen` and opens Version 4 with `status = "Open"`, `is_current = TRUE`.
- **In Gold Analytics:** `gold_reopened_analysis` calculates:
  $$\text{Reopen Rate (\%)} = \frac{\sum \text{is\_reopened}}{\text{Total Complaints}} \times 100$$
  This immediately alerts agency commissioners if a contractor or district is prematurely closing tickets to falsify SLA compliance.

---

## 4. Data Quality Firewall & Quarantine (DLQ)

### **Interview Talking Point:**
> *"How do you prevent dirty operational data from polluting your warehouse?"*

### **The Technical Implementation:**
1. **Rule Engine:**
   - **Rule 1 (Identity):** Rejects missing `service_request_id` or `sr_type`.
   - **Rule 2 (Status Domain):** Rejects unknown status strings.
   - **Rule 3 (Temporal Logic):** Catches temporal paradoxes where `closed_date < created_date`.
   - **Rule 4 (Geospatial Bounds):** Validates coordinates against Chicago municipal limits ($41.644 \le \text{Lat} \le 42.023$, $-87.940 \le \text{Lon} \le -87.524$).
2. **Dead-Letter Queue (DLQ):**
   - Violations are not discarded; they are isolated to `quarantine/year=YYYY/month=MM/day=DD/quarantine_{id}.json` with:
     - `raw_payload`: Unaltered source payload
     - `failed_rules`: Array of rule failure codes
     - `rejection_reason`: Primary cause
   - Valid records continue downstream to Silver uninterrupted.

---

## 5. Schema Evolution

### **Interview Talking Point:**
> *"How does the pipeline handle when the municipality introduces new fields to the 311 API?"*

### **The Technical Implementation:**
- In the Ingestion layer, our Pydantic model uses `model_config = ConfigDict(extra="allow")`, preventing crashes when unknown keys appear.
- In Silver and BigQuery, known structural columns are typed strictly, while newly introduced attributes are dynamically packaged into a native `extended_attributes JSON` column.
- This allows data analysts to query newly introduced fields immediately via BigQuery JSON path expressions (e.g., `extended_attributes.citizen_reopen_reason`) without requiring schema migrations or pipeline downtime.

---

## 6. Backfilling Historical Periods

### **Interview Talking Point:**
> *"How do you backfill 6 months of historical data without disrupting continuous incremental ingestion?"*

### **The Technical Implementation:**
- CivicPulse provides a dedicated backfill mode:
  ```bash
  python src/pipeline.py backfill --start-date 2024-01-01 --end-date 2024-06-01 --mode live
  ```
- **Isolation Principle:** Backfill queries target bounded date windows (`last_modified_date >= start AND last_modified_date <= end`).
- It stages the data into raw partition snapshots labeled with a `backfill_` batch prefix.
- Crucially, it **does not modify the forward-moving production watermark** in `watermark_state.json`, ensuring standard daily scheduled ingestion continues smoothly.

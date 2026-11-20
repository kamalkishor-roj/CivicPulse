-- =====================================================================
-- BigQuery SCD Type 2 Incremental MERGE Pattern
-- Updates existing active records (is_current=TRUE -> FALSE) when status changes,
-- and inserts new version rows with is_current=TRUE.
-- =====================================================================

MERGE `@project_id.@silver_dataset.dim_service_request_status_history` T
USING (
  -- Identify status transitions from incoming batch
  WITH ranked_events AS (
    SELECT
      service_request_id,
      status,
      effective_start_date,
      LEAD(effective_start_date) OVER(
        PARTITION BY service_request_id ORDER BY effective_start_date ASC
      ) AS computed_end_date,
      ROW_NUMBER() OVER(
        PARTITION BY service_request_id ORDER BY effective_start_date ASC
      ) AS version_num
    FROM `@project_id.@silver_dataset.tmp_incoming_status_events`
  )
  SELECT
    MD5(CONCAT(service_request_id, '_', status, '_', CAST(effective_start_date AS STRING))) AS status_history_sk,
    service_request_id,
    status,
    effective_start_date,
    computed_end_date AS effective_end_date,
    (computed_end_date IS NULL) AS is_current,
    version_num AS version,
    ROUND(TIMESTAMP_DIFF(computed_end_date, effective_start_date, SECOND) / 3600.0, 2) AS duration_in_status_hours,
    version_num AS status_sequence_order,
    CURRENT_TIMESTAMP() AS created_at
  FROM ranked_events
) S
ON T.status_history_sk = S.status_history_sk
WHEN MATCHED AND (T.is_current != S.is_current OR T.effective_end_date != S.effective_end_date) THEN
  UPDATE SET
    T.effective_end_date = S.effective_end_date,
    T.is_current = S.is_current,
    T.duration_in_status_hours = S.duration_in_status_hours
WHEN NOT MATCHED THEN
  INSERT (
    status_history_sk,
    service_request_id,
    status,
    effective_start_date,
    effective_end_date,
    is_current,
    version,
    duration_in_status_hours,
    status_sequence_order,
    created_at
  )
  VALUES (
    S.status_history_sk,
    S.service_request_id,
    S.status,
    S.effective_start_date,
    S.effective_end_date,
    S.is_current,
    S.version,
    S.duration_in_status_hours,
    S.status_sequence_order,
    S.created_at
  );

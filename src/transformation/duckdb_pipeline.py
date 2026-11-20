"""
DuckDB Transformation Engine for CivicPulse
High-performance in-process SQL execution of Medallion transformations (Bronze -> Silver -> Gold).
"""

import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import duckdb
import pandas as pd
from config.settings import settings
from config.logging_config import logger
from src.common.storage import StorageBackend
from src.transformation.quality import DataQualityValidator
from src.transformation.change_detector import ChangeDetector
from src.transformation.scd_processor import SCDType2Processor


class DuckDBPipeline:
    """
    Executes the Medallion architecture transformations using DuckDB.
    """

    def __init__(self, storage: StorageBackend, db_path: Optional[str] = None, read_only: bool = False):
        self.storage = storage
        self.db_path = db_path or str(settings.local_data_dir / "civicpulse.duckdb")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.read_only = read_only
        try:
            self.con = duckdb.connect(database=self.db_path, read_only=read_only)
        except Exception as e:
            if not read_only:
                logger.warning(f"Could not open in read-write mode ({e}), falling back to read_only=True")
                self.con = duckdb.connect(database=self.db_path, read_only=True)
                self.read_only = True
            else:
                raise
        self.validator = DataQualityValidator(storage)
        if not self.read_only:
            self._init_schemas()

    def _init_schemas(self) -> None:
        """Initializes tables for Bronze, Silver, SCD Type 2, and Gold marts."""
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS bronze_service_requests (
                raw_payload VARCHAR,
                service_request_id VARCHAR,
                sr_type VARCHAR,
                status VARCHAR,
                created_date VARCHAR,
                last_modified_date VARCHAR,
                closed_date VARCHAR,
                owner_department VARCHAR,
                street_address VARCHAR,
                zip_code VARCHAR,
                ward VARCHAR,
                latitude VARCHAR,
                longitude VARCHAR,
                ingested_at TIMESTAMP,
                source_batch_id VARCHAR
            );

            CREATE TABLE IF NOT EXISTS silver_service_requests (
                service_request_id VARCHAR PRIMARY KEY,
                sr_type VARCHAR,
                sr_short_code VARCHAR,
                agency VARCHAR,
                status VARCHAR,
                created_date TIMESTAMP,
                last_modified_date TIMESTAMP,
                closed_date TIMESTAMP,
                resolution_time_hours DOUBLE,
                street_address VARCHAR,
                zip_code VARCHAR,
                ward INTEGER,
                community_area INTEGER,
                police_district INTEGER,
                latitude DOUBLE,
                longitude DOUBLE,
                is_duplicate BOOLEAN,
                is_reopened BOOLEAN,
                record_hash VARCHAR,
                extended_attributes VARCHAR,
                updated_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS dim_service_request_status_history (
                status_history_sk VARCHAR PRIMARY KEY,
                service_request_id VARCHAR,
                status VARCHAR,
                effective_start_date TIMESTAMP,
                effective_end_date TIMESTAMP,
                is_current BOOLEAN,
                version INTEGER,
                duration_in_status_hours DOUBLE,
                status_sequence_order INTEGER,
                created_at TIMESTAMP
            );
        """)
        logger.info("Initialized DuckDB database schemas (Bronze, Silver, SCD2).")

    def process_raw_files(self, raw_file_paths: List[str]) -> Dict[str, Any]:
        """
        Reads raw JSON files, validates records, updates Bronze and Silver layers,
        and computes SCD Type 2 status history.
        """
        all_raw_records = []
        batch_ids = set()

        for fp in raw_file_paths:
            try:
                data = self.storage.read_json(fp)
                b_id = data.get("batch_id", "unknown")
                batch_ids.add(b_id)
                for rec in data.get("records", []):
                    rec["_source_batch_id"] = b_id
                    all_raw_records.append(rec)
            except Exception as e:
                logger.error(f"Error reading raw snapshot {fp}: {e}")

        if not all_raw_records:
            logger.info("No raw records to transform.")
            return {"status": "EMPTY", "records_processed": 0}

        # Step 1: Load Bronze
        bronze_rows = []
        import json
        for r in all_raw_records:
            req_id = r.get("sr_number") or r.get("service_request_id")
            bronze_rows.append((
                json.dumps(r, default=str),
                str(req_id) if req_id else None,
                str(r.get("sr_type") or r.get("type_of_service_request")),
                str(r.get("status")),
                str(r.get("created_date")),
                str(r.get("last_modified_date")),
                str(r.get("closed_date")),
                str(r.get("owner_department") or r.get("agency_responsible")),
                str(r.get("street_address")),
                str(r.get("zip_code")),
                str(r.get("ward")),
                str(r.get("latitude")),
                str(r.get("longitude")),
                pd.Timestamp.utcnow(),
                r.get("_source_batch_id")
            ))

        self.con.executemany("""
            INSERT INTO bronze_service_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, bronze_rows)
        logger.info(f"Loaded {len(bronze_rows)} records into bronze_service_requests.")

        # Step 2: Data Quality & Quarantine
        first_batch = list(batch_ids)[0] if batch_ids else "batch_00"
        valid_records, quarantined = self.validator.partition_and_quarantine(all_raw_records, first_batch)

        # Step 3: Group by request ID to construct SCD2 and resolve latest state
        records_by_id: Dict[str, List[Dict[str, Any]]] = {}
        for r in valid_records:
            rid = r.get("sr_number") or r.get("service_request_id")
            if rid:
                records_by_id.setdefault(str(rid), []).append(r)

        silver_records = []
        all_scd2_records = []

        for req_id, events in records_by_id.items():
            # Build SCD Type 2 timeline
            scd2_timeline = SCDType2Processor.build_timeline_from_events(req_id, events)
            all_scd2_records.extend(scd2_timeline)

            # Determine latest record state (deduplication & change detection)
            events.sort(key=lambda x: str(x.get("last_modified_date") or x.get("created_date")), reverse=True)
            latest = events[0]

            # Detect reopenings: Did status go from Completed -> Open at any point?
            statuses_seen = [str(e.get("status", "")).strip().lower() for e in reversed(events)]
            is_reopened = False
            for i in range(len(statuses_seen) - 1):
                if statuses_seen[i] in {"completed", "closed"} and statuses_seen[i + 1] in {"open", "in progress"}:
                    is_reopened = True
                    break

            # Parse dates
            created_dt = self.validator._parse_iso(latest.get("created_date"))
            modified_dt = self.validator._parse_iso(latest.get("last_modified_date") or latest.get("created_date"))
            closed_dt = self.validator._parse_iso(latest.get("closed_date"))

            resolution_hours = None
            if created_dt and closed_dt:
                resolution_hours = max(0.0, round((closed_dt - created_dt).total_seconds() / 3600.0, 2))

            # Coordinates & Geo
            def _to_float(v):
                try:
                    return float(v) if v is not None else None
                except Exception:
                    return None

            def _to_int(v):
                try:
                    return int(v) if v is not None else None
                except Exception:
                    return None

            # Collect extended attributes for schema evolution
            core_keys = {"sr_number", "service_request_id", "sr_type", "type_of_service_request",
                         "sr_short_code", "owner_department", "agency_responsible", "status",
                         "created_date", "last_modified_date", "closed_date", "street_address",
                         "zip_code", "ward", "community_area", "police_district", "latitude",
                         "longitude", "duplicate", "legacy_record", "_source_batch_id"}
            extended_attrs = {k: v for k, v in latest.items() if k not in core_keys}

            silver_records.append({
                "service_request_id": req_id,
                "sr_type": latest.get("sr_type") or latest.get("type_of_service_request") or "Unknown",
                "sr_short_code": latest.get("sr_short_code"),
                "agency": latest.get("owner_department") or latest.get("agency_responsible") or "Unknown Agency",
                "status": str(latest.get("status", "Open")).title(),
                "created_date": created_dt,
                "last_modified_date": modified_dt,
                "closed_date": closed_dt,
                "resolution_time_hours": resolution_hours,
                "street_address": latest.get("street_address"),
                "zip_code": latest.get("zip_code"),
                "ward": _to_int(latest.get("ward")),
                "community_area": _to_int(latest.get("community_area")),
                "police_district": _to_int(latest.get("police_district")),
                "latitude": _to_float(latest.get("latitude")),
                "longitude": _to_float(latest.get("longitude")),
                "is_duplicate": bool(latest.get("duplicate", False)),
                "is_reopened": is_reopened,
                "record_hash": ChangeDetector.compute_record_hash(latest),
                "extended_attributes": json.dumps(extended_attrs, default=str),
                "updated_at": pd.Timestamp.utcnow()
            })

        # Step 4: Upsert into Silver table
        if silver_records:
            silver_df = pd.DataFrame(silver_records)
            self.con.register("tmp_silver_updates", silver_df)
            self.con.execute("""
                DELETE FROM silver_service_requests
                WHERE service_request_id IN (SELECT service_request_id FROM tmp_silver_updates);

                INSERT INTO silver_service_requests
                SELECT * FROM tmp_silver_updates;
            """)
            logger.info(f"Upserted {len(silver_records)} distinct service requests into silver_service_requests.")

        # Step 5: Upsert into SCD Type 2 dimension
        if all_scd2_records:
            scd2_df = pd.DataFrame([s.model_dump() for s in all_scd2_records])
            self.con.register("tmp_scd2_updates", scd2_df)
            self.con.execute("""
                DELETE FROM dim_service_request_status_history
                WHERE status_history_sk IN (SELECT status_history_sk FROM tmp_scd2_updates);

                INSERT INTO dim_service_request_status_history
                SELECT * FROM tmp_scd2_updates;
            """)
            logger.info(f"Updated {len(all_scd2_records)} SCD Type 2 status history intervals.")

        # Step 6: Refresh Gold Analytics Marts
        self.refresh_gold_marts()

        return {
            "status": "SUCCESS",
            "total_raw": len(all_raw_records),
            "valid_records": len(valid_records),
            "quarantined_records": len(quarantined),
            "silver_entities": len(silver_records),
            "scd2_intervals": len(all_scd2_records)
        }

    def refresh_gold_marts(self) -> None:
        """
        Re-computes Gold Aggregation Data Marts answering core infrastructure intelligence questions.
        """
        # Gold Mart 1: Resolution Time by Complaint Category
        self.con.execute("""
            CREATE OR REPLACE TABLE gold_resolution_time_by_category AS
            SELECT
                sr_type,
                COUNT(*) AS total_complaints,
                COUNT(closed_date) AS resolved_complaints,
                ROUND(AVG(resolution_time_hours), 2) AS avg_resolution_hours,
                ROUND(MEDIAN(resolution_time_hours), 2) AS median_resolution_hours,
                ROUND(QUANTILE_CONT(resolution_time_hours, 0.90), 2) AS p90_resolution_hours,
                ROUND(MIN(resolution_time_hours), 2) AS min_resolution_hours,
                ROUND(MAX(resolution_time_hours), 2) AS max_resolution_hours
            FROM silver_service_requests
            WHERE closed_date IS NOT NULL
            GROUP BY sr_type
            ORDER BY avg_resolution_hours DESC;
        """)

        # Gold Mart 2: Agency Backlog and Ageing Buckets
        self.con.execute("""
            CREATE OR REPLACE TABLE gold_agency_backlog AS
            SELECT
                agency,
                COUNT(*) AS total_open_backlog,
                SUM(CASE WHEN DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) < 7 THEN 1 ELSE 0 END) AS backlog_under_7d,
                SUM(CASE WHEN DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) BETWEEN 7 AND 30 THEN 1 ELSE 0 END) AS backlog_7_to_30d,
                SUM(CASE WHEN DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) BETWEEN 31 AND 90 THEN 1 ELSE 0 END) AS backlog_31_to_90d,
                SUM(CASE WHEN DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) > 90 THEN 1 ELSE 0 END) AS backlog_over_90d,
                ROUND(AVG(DATE_DIFF('day', created_date, CURRENT_TIMESTAMP)), 1) AS avg_backlog_age_days
            FROM silver_service_requests
            WHERE status NOT IN ('Completed', 'Closed', 'Cancelled')
            GROUP BY agency
            ORDER BY total_open_backlog DESC;
        """)

        # Gold Mart 3: Geographic Hotspots (Wards & Zip Codes)
        self.con.execute("""
            CREATE OR REPLACE TABLE gold_geographic_hotspots AS
            SELECT
                ward,
                zip_code,
                sr_type,
                COUNT(*) AS complaint_count,
                ROUND(AVG(CASE WHEN closed_date IS NOT NULL THEN resolution_time_hours ELSE NULL END), 2) AS avg_resolution_hours,
                SUM(CASE WHEN is_reopened THEN 1 ELSE 0 END) AS reopened_count
            FROM silver_service_requests
            WHERE ward IS NOT NULL
            GROUP BY ward, zip_code, sr_type
            ORDER BY complaint_count DESC;
        """)

        # Gold Mart 4: Longest Resolving Complaints (Bottleneck Analysis)
        self.con.execute("""
            CREATE OR REPLACE TABLE gold_longest_resolving_complaints AS
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
            FROM silver_service_requests
            WHERE resolution_time_hours IS NOT NULL
            ORDER BY resolution_time_hours DESC
            LIMIT 50;
        """)

        # Gold Mart 5: Reopened Complaints Analysis
        self.con.execute("""
            CREATE OR REPLACE TABLE gold_reopened_analysis AS
            SELECT
                agency,
                sr_type,
                COUNT(*) AS total_complaints,
                SUM(CASE WHEN is_reopened THEN 1 ELSE 0 END) AS reopened_count,
                ROUND(100.0 * SUM(CASE WHEN is_reopened THEN 1 ELSE 0 END) / COUNT(*), 2) AS reopen_percentage
            FROM silver_service_requests
            GROUP BY agency, sr_type
            ORDER BY reopen_percentage DESC, reopened_count DESC;
        """)

        logger.info("Successfully refreshed all 5 Gold Analytics Marts in DuckDB.")

    def query(self, sql: str) -> pd.DataFrame:
        """Executes SQL and returns a Pandas DataFrame."""
        return self.con.execute(sql).df()

    def close(self) -> None:
        """Closes DuckDB connection."""
        self.con.close()

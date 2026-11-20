"""
CivicPulse FastAPI Backend Service
Provides high-performance REST APIs for the React Executive Dashboard, querying DuckDB Lakehouse.
"""

import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import pandas as pd

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from config.logging_config import logger
from src.common.storage import get_storage_backend
from src.transformation.duckdb_pipeline import DuckDBPipeline
from src.analytics.marts import AnalyticsService
from src.common.state_manager import StateManager
from src.pipeline import CivicPulseOrchestrator

app = FastAPI(
    title="CivicPulse Public Infrastructure API",
    description="REST backend powering the CivicPulse React Executive Intelligence Platform",
    version="2.0.0"
)

# Enable CORS for local React development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


def escape_sql(s: Optional[str]) -> str:
    if not s:
        return ""
    return str(s).replace("'", "''")


def get_pipeline() -> DuckDBPipeline:
    storage = get_storage_backend(
        backend_type=settings.storage_backend,
        base_dir=settings.local_data_dir,
        bucket_name=settings.gcs_raw_bucket,
        project_id=settings.gcp_project_id
    )
    return DuckDBPipeline(storage=storage, read_only=True)


@app.get("/api/kpis")
def get_kpis(
    agency: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Calculates executive KPI metrics based on active filters."""
    pipe = get_pipeline()
    where_clauses = ["1=1"]
    if agency and agency != "ALL":
        where_clauses.append(f"agency = '{escape_sql(agency)}'")
    if category and category != "ALL":
        where_clauses.append(f"sr_type = '{escape_sql(category)}'")
    if status == "BACKLOG":
        where_clauses.append("status NOT IN ('Completed', 'Closed', 'Cancelled')")
    elif status == "RESOLVED":
        where_clauses.append("closed_date IS NOT NULL")
    elif status == "REOPENED":
        where_clauses.append("is_reopened = TRUE")

    where_sql = " AND ".join(where_clauses)
    try:
        df = pipe.query(f"""
            SELECT
                COUNT(*) AS total_complaints,
                COUNT(closed_date) AS total_resolved,
                COUNT(*) - COUNT(closed_date) AS total_active_backlog,
                ROUND(AVG(resolution_time_hours), 1) AS avg_resolution_hours,
                ROUND(100.0 * SUM(CASE WHEN is_reopened THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS reopen_rate_pct,
                SUM(CASE WHEN status NOT IN ('Completed', 'Closed', 'Cancelled') AND DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) > 30 THEN 1 ELSE 0 END) AS critical_backlog_30d
            FROM silver_service_requests
            WHERE {where_sql};
        """)
        row = df.iloc[0].to_dict() if not df.empty else {}
        total = int(row.get("total_complaints") or 0)
        resolved = int(row.get("total_resolved") or 0)
        backlog = int(row.get("total_active_backlog") or 0)
        return {
            "total_complaints": total,
            "total_resolved": resolved,
            "total_backlog": backlog,
            "resolution_rate_pct": round((resolved / total * 100), 1) if total > 0 else 0.0,
            "avg_resolution_hours": float(row.get("avg_resolution_hours") or 0.0),
            "reopen_rate_pct": float(row.get("reopen_rate_pct") or 0.0),
            "critical_backlog_30d": int(row.get("critical_backlog_30d") or 0)
        }
    finally:
        pipe.close()


@app.get("/api/resolution-velocity")
def get_resolution_velocity(
    agency: Optional[str] = Query(None)
) -> List[Dict[str, Any]]:
    """Returns average, median, and P90 resolution times by complaint type."""
    pipe = get_pipeline()
    where_sql = f"agency = '{escape_sql(agency)}'" if agency and agency != "ALL" else "1=1"
    try:
        df = pipe.query(f"""
            SELECT
                sr_type,
                COUNT(closed_date) AS resolved_count,
                ROUND(AVG(resolution_time_hours), 1) AS avg_hours,
                ROUND(MEDIAN(resolution_time_hours), 1) AS median_hours,
                ROUND(QUANTILE_CONT(resolution_time_hours, 0.90), 1) AS p90_hours
            FROM silver_service_requests
            WHERE closed_date IS NOT NULL AND {where_sql}
            GROUP BY sr_type
            ORDER BY avg_hours DESC;
        """)
        return df.to_dict(orient="records")
    finally:
        pipe.close()


@app.get("/api/agency-backlogs")
def get_agency_backlogs() -> List[Dict[str, Any]]:
    """Returns open backlog volume segmented into 4 ageing brackets."""
    pipe = get_pipeline()
    try:
        df = pipe.query("""
            SELECT
                agency,
                COUNT(*) AS total_backlog,
                SUM(CASE WHEN DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) < 7 THEN 1 ELSE 0 END) AS backlog_under_7d,
                SUM(CASE WHEN DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) BETWEEN 7 AND 30 THEN 1 ELSE 0 END) AS backlog_7_to_30d,
                SUM(CASE WHEN DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) BETWEEN 31 AND 90 THEN 1 ELSE 0 END) AS backlog_31_to_90d,
                SUM(CASE WHEN DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) > 90 THEN 1 ELSE 0 END) AS backlog_over_90d,
                ROUND(AVG(DATE_DIFF('day', created_date, CURRENT_TIMESTAMP)), 1) AS avg_age_days
            FROM silver_service_requests
            WHERE status NOT IN ('Completed', 'Closed', 'Cancelled')
            GROUP BY agency
            ORDER BY total_backlog DESC;
        """)
        return df.to_dict(orient="records")
    finally:
        pipe.close()


@app.get("/api/map-points")
def get_map_points(
    agency: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = 500
) -> List[Dict[str, Any]]:
    """Returns geospatial coordinates for interactive Leaflet.js mapping (Zero API key needed)."""
    pipe = get_pipeline()
    where_clauses = ["latitude IS NOT NULL", "longitude IS NOT NULL"]
    if agency and agency != "ALL":
        where_clauses.append(f"agency = '{escape_sql(agency)}'")
    if category and category != "ALL":
        where_clauses.append(f"sr_type = '{escape_sql(category)}'")

    where_sql = " AND ".join(where_clauses)
    try:
        df = pipe.query(f"""
            SELECT
                service_request_id,
                sr_type,
                agency,
                status,
                ward,
                street_address,
                latitude,
                longitude,
                created_date,
                is_reopened
            FROM silver_service_requests
            WHERE {where_sql}
            LIMIT {limit};
        """)
        # Convert timestamps to strings for JSON serialization
        df["created_date"] = df["created_date"].astype(str)
        return df.to_dict(orient="records")
    finally:
        pipe.close()


@app.get("/api/scd2/candidates")
def get_scd2_candidates() -> List[Dict[str, Any]]:
    """Returns candidate service requests for SCD Type 2 status history inspection."""
    pipe = get_pipeline()
    try:
        df = pipe.query("""
            SELECT
                s.service_request_id,
                s.sr_type,
                s.agency,
                s.status AS current_status,
                s.is_reopened,
                COUNT(h.status_history_sk) AS transition_count
            FROM silver_service_requests s
            JOIN dim_service_request_status_history h USING (service_request_id)
            GROUP BY s.service_request_id, s.sr_type, s.agency, s.status, s.is_reopened
            ORDER BY transition_count DESC, s.is_reopened DESC
            LIMIT 50;
        """)
        return df.to_dict(orient="records")
    finally:
        pipe.close()


@app.get("/api/scd2/history/{service_request_id}")
def get_scd2_history(service_request_id: str) -> List[Dict[str, Any]]:
    """Returns complete chronological status history timeline for a single request."""
    pipe = get_pipeline()
    try:
        df = pipe.query(f"""
            SELECT
                version,
                status,
                effective_start_date,
                effective_end_date,
                is_current,
                duration_in_status_hours,
                status_history_sk
            FROM dim_service_request_status_history
            WHERE service_request_id = '{escape_sql(service_request_id)}'
            ORDER BY version ASC;
        """)
        df["effective_start_date"] = df["effective_start_date"].astype(str)
        df["effective_end_date"] = df["effective_end_date"].fillna("ACTIVE").astype(str)
        return df.to_dict(orient="records")
    finally:
        pipe.close()


@app.get("/api/quarantine")
def get_quarantine_violations() -> Dict[str, Any]:
    """Returns Dead-Letter Queue (DLQ) validation failure statistics and records."""
    storage = get_storage_backend(backend_type=settings.storage_backend, base_dir=settings.local_data_dir)
    q_files = storage.list_files("quarantine", suffix=".json")
    all_violations = []
    for qf in q_files[-5:]:
        try:
            records = storage.read_json(qf)
            if isinstance(records, list):
                all_violations.extend(records)
        except Exception:
            pass

    reasons = {}
    for r in all_violations:
        reason = r.get("rejection_reason", "Validation Failure")
        reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "total_quarantined": len(all_violations),
        "reasons_breakdown": reasons,
        "sample_records": all_violations[:20]
    }


@app.post("/api/ingest")
def trigger_ingestion() -> Dict[str, Any]:
    """Triggers an incremental ingestion run from current watermark."""
    orch = CivicPulseOrchestrator()
    res = orch.run_end_to_end(mode="mock", max_records=250)
    return {"status": "SUCCESS", "message": "Batch ingested and lakehouse updated", "details": res}


@app.get("/api/state")
def get_pipeline_state() -> Dict[str, Any]:
    """Returns watermark and pipeline status."""
    storage = get_storage_backend(backend_type=settings.storage_backend, base_dir=settings.local_data_dir)
    state_mgr = StateManager(storage=storage)
    return state_mgr.current_state.model_dump()


# Mount static directory and serve React application
@app.get("/")
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="React frontend index.html not found.")
    return FileResponse(index_file)

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main():
    logger.info("Starting CivicPulse FastAPI Web Server on http://localhost:8000 ...")
    uvicorn.run("app.api:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()

"""
Analytics and Gold Marts Provider
Exposes typed analytical dataframes and summaries for executive dashboards and reporting.
"""

from typing import Dict, Any, List
import pandas as pd
from config.logging_config import logger
from src.transformation.duckdb_pipeline import DuckDBPipeline


class AnalyticsService:
    """
    Exposes high-level analytical queries against Gold layer data marts.
    """

    def __init__(self, pipeline: DuckDBPipeline):
        self.pipeline = pipeline

    def get_executive_summary(self) -> Dict[str, Any]:
        """
        Calculates high-level city infrastructure KPIs.
        """
        df_overall = self.pipeline.query("""
            SELECT
                COUNT(*) AS total_complaints,
                COUNT(closed_date) AS total_resolved,
                COUNT(*) - COUNT(closed_date) AS total_active_backlog,
                ROUND(AVG(resolution_time_hours), 1) AS avg_resolution_hours,
                ROUND(100.0 * SUM(CASE WHEN is_reopened THEN 1 ELSE 0 END) / COUNT(*), 2) AS reopen_rate_pct
            FROM silver_service_requests;
        """)

        df_backlog_30d = self.pipeline.query("""
            SELECT COUNT(*) AS critical_backlog
            FROM silver_service_requests
            WHERE status NOT IN ('Completed', 'Closed', 'Cancelled')
              AND DATE_DIFF('day', created_date, CURRENT_TIMESTAMP) > 30;
        """)

        res = df_overall.iloc[0].to_dict()
        res["critical_backlog_over_30d"] = int(df_backlog_30d.iloc[0]["critical_backlog"])
        return res

    def get_resolution_time_by_category(self) -> pd.DataFrame:
        """Resolution time metrics across complaint categories."""
        return self.pipeline.query("""
            SELECT * FROM gold_resolution_time_by_category
            ORDER BY avg_resolution_hours DESC;
        """)

    def get_agency_backlog(self) -> pd.DataFrame:
        """Agency backlogs split by ageing brackets."""
        return self.pipeline.query("""
            SELECT * FROM gold_agency_backlog
            ORDER BY total_open_backlog DESC;
        """)

    def get_geographic_hotspots(self, limit: int = 20) -> pd.DataFrame:
        """Top recurring infrastructure failure zones by ward."""
        return self.pipeline.query(f"""
            SELECT * FROM gold_geographic_hotspots
            ORDER BY complaint_count DESC
            LIMIT {limit};
        """)

    def get_longest_resolving_complaints(self, limit: int = 25) -> pd.DataFrame:
        """Specific complaints experiencing extreme resolution delays."""
        return self.pipeline.query(f"""
            SELECT * FROM gold_longest_resolving_complaints
            LIMIT {limit};
        """)

    def get_reopened_complaints_analysis(self) -> pd.DataFrame:
        """Recidivism / reopen rates by agency and request type."""
        return self.pipeline.query("""
            SELECT * FROM gold_reopened_analysis
            ORDER BY reopen_percentage DESC;
        """)

    def get_service_request_lifecycle(self, request_id: str) -> pd.DataFrame:
        """
        Retrieves the complete SCD Type 2 status trajectory for a given complaint.
        """
        return self.pipeline.query(f"""
            SELECT
                version,
                status,
                effective_start_date,
                effective_end_date,
                is_current,
                duration_in_status_hours
            FROM dim_service_request_status_history
            WHERE service_request_id = '{request_id}'
            ORDER BY version ASC;
        """)

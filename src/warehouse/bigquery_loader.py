"""
Google Cloud BigQuery Warehouse Loader
Manages dataset creation, table partitioning, clustered table definitions, and view creation.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from config.settings import settings
from config.logging_config import logger


class BigQueryLoader:
    """
    Client for provisioning BigQuery datasets, tables, and executing Medallion transformations.
    """

    def __init__(self, project_id: Optional[str] = None, location: Optional[str] = None):
        self.project_id = project_id or settings.gcp_project_id
        self.location = location or settings.bigquery_location
        self.client = None
        self._init_client()

    def _init_client(self):
        try:
            from google.cloud import bigquery
            self.client = bigquery.Client(project=self.project_id, location=self.location)
            logger.info(f"BigQueryLoader connected to GCP project '{self.project_id}' in region '{self.location}'")
        except Exception as e:
            logger.warning(f"Could not connect to BigQuery ({e}). Operating in Local/Dry-Run mode.")
            self.client = None

    def execute_sql(self, sql_template: str) -> None:
        """
        Substitutes project and dataset template variables and executes SQL query in BigQuery.
        """
        rendered_sql = (
            sql_template.replace("@project_id", self.project_id)
            .replace("@location", self.location)
            .replace("@bronze_dataset", settings.bq_bronze_dataset)
            .replace("@silver_dataset", settings.bq_silver_dataset)
            .replace("@gold_dataset", settings.bq_gold_dataset)
        )

        if not self.client:
            logger.info(f"[Dry-Run / Local Mode] SQL prepared for execution:\n{rendered_sql[:300]}...")
            return

        logger.info(f"Executing BigQuery SQL job...")
        query_job = self.client.query(rendered_sql)
        query_job.result()
        logger.info("BigQuery job completed successfully.")

    def apply_migrations(self, sql_dir: Optional[Path] = None) -> None:
        """
        Executes Bronze, Silver, and Gold DDL scripts in order.
        """
        base_sql = sql_dir or (Path(__file__).resolve().parent / "sql")
        scripts = ["bronze_ddl.sql", "silver_ddl.sql", "gold_views.sql"]

        for script_name in scripts:
            script_path = base_sql / script_name
            if script_path.exists():
                logger.info(f"Applying BigQuery migration: {script_name}")
                with open(script_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.execute_sql(content)
            else:
                logger.warning(f"Migration file not found: {script_path}")

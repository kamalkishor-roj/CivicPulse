"""
CivicPulse Platform Configuration
Centralized configuration management with environment variable overrides and sensible defaults.
"""

from pathlib import Path
import os
from typing import Optional
from pydantic import BaseModel, Field

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

class Settings(BaseModel):
    # GCP Infrastructure
    gcp_project_id: str = Field(default="civicpulse-local-dev")
    gcp_region: str = Field(default="us-central1")
    gcs_raw_bucket: str = Field(default="civicpulse-raw-data-lake")
    bigquery_location: str = Field(default="US")

    # BigQuery Datasets (Medallion Architecture)
    bq_bronze_dataset: str = Field(default="civicpulse_bronze")
    bq_silver_dataset: str = Field(default="civicpulse_silver")
    bq_gold_dataset: str = Field(default="civicpulse_gold")

    # Storage and Engine Backends
    storage_backend: str = Field(default="local")  # 'local' or 'gcs'
    local_data_dir: Path = Field(default=DATA_DIR)
    processing_engine: str = Field(default="duckdb")  # 'duckdb' or 'pyspark'

    # Chicago 311 API Config
    chicago_311_endpoint: str = Field(default="https://data.cityofchicago.org/resource/v6vf-nfxy.json")
    socrata_app_token: Optional[str] = Field(default=None)
    socrata_app_secret: Optional[str] = Field(default=None)

    # Ingestion Controls
    ingestion_batch_size: int = Field(default=2000)
    ingestion_max_retries: int = Field(default=5)
    ingestion_backoff_factor: float = Field(default=2.0)
    ingestion_rate_limit_delay: float = Field(default=0.2)

    # Logging
    log_level: str = Field(default="INFO")

    # Data Quality Bounding Box (Chicago Municipal Limits)
    chicago_min_lat: float = 41.644
    chicago_max_lat: float = 42.023
    chicago_min_lon: float = -87.940
    chicago_max_lon: float = -87.524

    @classmethod
    def load(cls) -> "Settings":
        """Load settings with environment variable overrides."""
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=env_file)

        return cls(
            gcp_project_id=os.getenv("GCP_PROJECT_ID", "civicpulse-local-dev"),
            gcp_region=os.getenv("GCP_REGION", "us-central1"),
            gcs_raw_bucket=os.getenv("GCS_RAW_BUCKET", "civicpulse-raw-data-lake"),
            bigquery_location=os.getenv("BIGQUERY_LOCATION", "US"),
            bq_bronze_dataset=os.getenv("BQ_BRONZE_DATASET", "civicpulse_bronze"),
            bq_silver_dataset=os.getenv("BQ_SILVER_DATASET", "civicpulse_silver"),
            bq_gold_dataset=os.getenv("BQ_GOLD_DATASET", "civicpulse_gold"),
            storage_backend=os.getenv("STORAGE_BACKEND", "local").lower(),
            local_data_dir=Path(os.getenv("LOCAL_DATA_DIR", str(DATA_DIR))),
            processing_engine=os.getenv("PROCESSING_ENGINE", "duckdb").lower(),
            chicago_311_endpoint=os.getenv("CHICAGO_311_ENDPOINT", "https://data.cityofchicago.org/resource/v6vf-nfxy.json"),
            socrata_app_token=os.getenv("SOCRATA_APP_TOKEN"),
            socrata_app_secret=os.getenv("SOCRATA_APP_SECRET"),
            ingestion_batch_size=int(os.getenv("INGESTION_BATCH_SIZE", "2000")),
            ingestion_max_retries=int(os.getenv("INGESTION_MAX_RETRIES", "5")),
            ingestion_backoff_factor=float(os.getenv("INGESTION_BACKOFF_FACTOR", "2.0")),
            ingestion_rate_limit_delay=float(os.getenv("INGESTION_RATE_LIMIT_DELAY", "0.2")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

# Global singleton settings instance
settings = Settings.load()

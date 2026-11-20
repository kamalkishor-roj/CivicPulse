"""
CivicPulse CLI and End-to-End Orchestrator
Coordinates extraction, raw landing, data quality quarantine, Silver deduplication,
SCD Type 2 tracking, and Gold data mart generation.
"""

import sys
import argparse
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from typing import Optional
from config.settings import settings
from config.logging_config import logger
from src.common.storage import get_storage_backend
from src.common.state_manager import StateManager
from src.ingestion.extractor import IngestionExtractor
from src.transformation.duckdb_pipeline import DuckDBPipeline
from src.transformation.spark_pipeline import PySparkPipeline
from src.warehouse.bigquery_loader import BigQueryLoader


class CivicPulseOrchestrator:
    """
    Unified orchestrator managing the CivicPulse data platform pipeline.
    """

    def __init__(self):
        self.storage = get_storage_backend(
            backend_type=settings.storage_backend,
            base_dir=settings.local_data_dir,
            bucket_name=settings.gcs_raw_bucket,
            project_id=settings.gcp_project_id
        )
        self.state_manager = StateManager(storage=self.storage)
        self.extractor = IngestionExtractor(storage=self.storage, state_manager=self.state_manager)
        self.duckdb_pipe = DuckDBPipeline(storage=self.storage)

    def run_ingestion(self, mode: str = "live", max_records: Optional[int] = None):
        """Runs incremental ingestion and lands raw JSON snapshots."""
        logger.info(f"=== Starting Ingestion Stage (Mode: {mode}) ===")
        res = self.extractor.run_incremental(mode=mode, max_records=max_records)
        logger.info(f"Ingestion result: {res['status']} | Extracted: {res['records_extracted']} records | Watermark: {res['new_watermark']}")
        return res

    def run_backfill(self, start_date: str, end_date: str, mode: str = "live", max_records: Optional[int] = None):
        """Runs historical backfill for specified date range."""
        logger.info(f"=== Starting Backfill Stage [{start_date} to {end_date}] (Mode: {mode}) ===")
        res = self.extractor.run_backfill(start_date=start_date, end_date=end_date, mode=mode, max_records=max_records)
        logger.info(f"Backfill result: {res['status']} | Extracted: {res['records_extracted']} records")
        return res

    def run_transformation(self, engine: str = "duckdb"):
        """Transforms raw partitioned files into Bronze, Silver, SCD2, and Gold layers."""
        logger.info(f"=== Starting Transformation Stage (Engine: {engine}) ===")
        raw_files = self.storage.list_files("raw", suffix=".json")
        if not raw_files:
            logger.warning("No raw files found in storage. Run ingestion first.")
            return {"status": "NO_RAW_DATA"}

        logger.info(f"Found {len(raw_files)} raw snapshot files to process.")

        if engine.lower() == "pyspark":
            spark_pipe = PySparkPipeline()
            try:
                res = spark_pipe.run_pipeline(raw_files)
                logger.info(f"PySpark transformation finished: {res}")
            finally:
                spark_pipe.stop()
            # Also sync into DuckDB so local dashboard can consume immediately
            res_duck = self.duckdb_pipe.process_raw_files(raw_files)
            return res_duck
        else:
            res = self.duckdb_pipe.process_raw_files(raw_files)
            logger.info(f"DuckDB transformation finished: {res}")
            return res

    def run_end_to_end(self, mode: str = "mock", max_records: int = 400, engine: str = "duckdb"):
        """Executes full pipeline: Ingestion -> Raw Landing -> DQ Validation -> Silver -> SCD2 -> Gold."""
        logger.info("=====================================================")
        logger.info("    CivicPulse End-to-End Data Pipeline Execution   ")
        logger.info("=====================================================")
        
        # 1. Ingestion
        ingest_res = self.run_ingestion(mode=mode, max_records=max_records)

        # 2. Transformation
        transform_res = self.run_transformation(engine=engine)

        logger.info("=====================================================")
        logger.info("Pipeline Run Complete!")
        logger.info(f"Records Ingested: {ingest_res.get('records_extracted', 0)}")
        logger.info(f"Valid Entities in Silver: {transform_res.get('silver_entities', 0)}")
        logger.info(f"Quarantined in DLQ: {transform_res.get('quarantined_records', 0)}")
        logger.info(f"SCD Type 2 Intervals: {transform_res.get('scd2_intervals', 0)}")
        logger.info("=====================================================")
        return {
            "ingestion": ingest_res,
            "transformation": transform_res
        }


def main():
    parser = argparse.ArgumentParser(description="CivicPulse Data Platform CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Run end-to-end pipeline")
    run_parser.add_argument("--mode", choices=["live", "mock"], default="mock", help="Ingestion mode ('live' for Socrata API, 'mock' for simulation)")
    run_parser.add_argument("--max-records", type=int, default=400, help="Max records to extract")
    run_parser.add_argument("--engine", choices=["duckdb", "pyspark"], default="duckdb", help="Processing engine")

    # Subcommand: ingest
    ingest_parser = subparsers.add_parser("ingest", help="Run raw ingestion only")
    ingest_parser.add_argument("--mode", choices=["live", "mock"], default="mock")
    ingest_parser.add_argument("--max-records", type=int, default=500)

    # Subcommand: backfill
    backfill_parser = subparsers.add_parser("backfill", help="Run historical backfill")
    backfill_parser.add_argument("--start-date", required=True, help="ISO start date (e.g. 2024-01-01)")
    backfill_parser.add_argument("--end-date", required=True, help="ISO end date (e.g. 2024-01-15)")
    backfill_parser.add_argument("--mode", choices=["live", "mock"], default="mock")
    backfill_parser.add_argument("--max-records", type=int, default=300)

    # Subcommand: transform
    transform_parser = subparsers.add_parser("transform", help="Run transformation on raw data")
    transform_parser.add_argument("--engine", choices=["duckdb", "pyspark"], default="duckdb")

    # Subcommand: status
    subparsers.add_parser("status", help="Show pipeline watermark and state")

    args = parser.parse_args()
    orchestrator = CivicPulseOrchestrator()

    if args.command == "run" or args.command is None:
        mode = getattr(args, "mode", "mock")
        max_rec = getattr(args, "max_records", 400)
        engine = getattr(args, "engine", "duckdb")
        orchestrator.run_end_to_end(mode=mode, max_records=max_rec, engine=engine)

    elif args.command == "ingest":
        orchestrator.run_ingestion(mode=args.mode, max_records=args.max_records)

    elif args.command == "backfill":
        orchestrator.run_backfill(
            start_date=args.start_date,
            end_date=args.end_date,
            mode=args.mode,
            max_records=args.max_records
        )

    elif args.command == "transform":
        orchestrator.run_transformation(engine=args.engine)

    elif args.command == "status":
        state = orchestrator.state_manager.current_state
        print("\n=== CivicPulse Pipeline Watermark State ===")
        print(f"Pipeline Name:     {state.pipeline_name}")
        print(f"Status:            {state.status}")
        print(f"Current Watermark: {state.last_extracted_watermark}")
        print(f"Total Extracted:   {state.total_records_extracted}")
        print(f"Last Run:          {state.last_run_timestamp}")
        print(f"Last Batch ID:     {state.last_batch_id}\n")


if __name__ == "__main__":
    main()

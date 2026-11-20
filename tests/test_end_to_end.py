"""
Integration Test for End-to-End Pipeline Execution
"""

from src.ingestion.extractor import IngestionExtractor
from src.transformation.duckdb_pipeline import DuckDBPipeline
from src.analytics.marts import AnalyticsService


def test_full_pipeline_flow(storage, state_manager, temp_dir):
    # 1. Ingestion
    extractor = IngestionExtractor(storage=storage, state_manager=state_manager)
    ingest_res = extractor.run_incremental(mode="mock", max_records=100)

    assert ingest_res["status"] == "SUCCESS"
    assert ingest_res["records_extracted"] > 0
    raw_files = storage.list_files("raw", suffix=".json")
    assert len(raw_files) > 0

    # 2. Transformation
    db_path = str(temp_dir / "test_e2e.duckdb")
    pipeline = DuckDBPipeline(storage=storage, db_path=db_path)
    transform_res = pipeline.process_raw_files(raw_files)

    assert transform_res["status"] == "SUCCESS"
    assert transform_res["silver_entities"] > 0
    assert transform_res["scd2_intervals"] > 0

    # 3. Analytics & Gold Marts
    analytics = AnalyticsService(pipeline=pipeline)
    summary = analytics.get_executive_summary()

    assert summary["total_complaints"] > 0
    assert "avg_resolution_hours" in summary

    df_res = analytics.get_resolution_time_by_category()
    assert not df_res.empty

    df_backlog = analytics.get_agency_backlog()
    assert df_backlog is not None

    pipeline.close()

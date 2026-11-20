"""
Unit Tests for Ingestion, Watermarking, and Failure Recovery
"""

from unittest.mock import MagicMock
from src.ingestion.extractor import IngestionExtractor


def test_watermark_initialization(state_manager):
    """Verify watermark initializes properly on first execution."""
    wm = state_manager.get_watermark()
    assert wm is not None
    assert "2024" in wm


def test_watermark_advancement_on_success(storage, state_manager):
    """Verify watermark advances only when records are ingested successfully."""
    extractor = IngestionExtractor(storage=storage, state_manager=state_manager)
    initial_wm = state_manager.get_watermark()

    res = extractor.run_incremental(mode="mock", max_records=50)

    assert res["status"] == "SUCCESS"
    assert res["records_extracted"] > 0
    new_wm = state_manager.get_watermark()
    assert new_wm > initial_wm
    assert state_manager.current_state.status == "SUCCESS"


def test_watermark_resilience_on_failure(storage, state_manager, monkeypatch):
    """
    CRITICAL INTERVIEW REQUIREMENT:
    Verify that if raw persistence or network fails, watermark is NOT advanced,
    allowing the pipeline to resume safely from the previous checkpoint.
    """
    extractor = IngestionExtractor(storage=storage, state_manager=state_manager)
    initial_wm = state_manager.get_watermark()

    original_write = storage.write_json

    def mock_fail_raw_write(path, data):
        if str(path).startswith("raw"):
            raise IOError("Disk full or GCS connection reset during ingestion!")
        return original_write(path, data)

    monkeypatch.setattr(storage, "write_json", mock_fail_raw_write)

    try:
        extractor.run_incremental(mode="mock", max_records=50)
    except IOError:
        pass

    # Watermark must NOT advance
    assert state_manager.get_watermark() == initial_wm
    assert state_manager.current_state.status == "FAILED"
    assert "connection reset" in state_manager.current_state.error_message


def test_backfill_does_not_corrupt_forward_watermark(storage, state_manager):
    """
    Verify historical backfill runs in isolation without modifying the forward-moving watermark.
    """
    extractor = IngestionExtractor(storage=storage, state_manager=state_manager)
    forward_wm = "2026-11-20T00:00:00.000"
    state_manager.commit_watermark(forward_wm, records_ingested=100, batch_id="test_b1")

    # Run historical backfill for an earlier month
    res = extractor.run_backfill(
        start_date="2024-01-01T00:00:00.000",
        end_date="2024-01-10T00:00:00.000",
        mode="mock",
        max_records=60
    )

    assert res["status"] == "SUCCESS"
    # Forward watermark must remain exactly as it was
    assert state_manager.get_watermark() == forward_wm

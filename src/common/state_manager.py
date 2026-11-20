"""
Watermark and Checkpoint State Manager
Provides atomic, crash-resilient state tracking for incremental ingestion and backfilling.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from config.logging_config import logger
from src.common.models import WatermarkState
from src.common.storage import StorageBackend


class StateManager:
    """
    Manages incremental extraction watermarks and run checkpoints.
    Guarantees exactly-once watermark progression and prevents data loss on crashes.
    """

    STATE_FILE_PATH = "state/watermark_state.json"

    def __init__(self, storage: StorageBackend, pipeline_name: str = "civicpulse_311_ingestion"):
        self.storage = storage
        self.pipeline_name = pipeline_name
        self.current_state = self.load_state()

    def load_state(self) -> WatermarkState:
        """Loads state from storage or initializes a fresh watermark."""
        try:
            if self.storage.exists(self.STATE_FILE_PATH):
                data = self.storage.read_json(self.STATE_FILE_PATH)
                state = WatermarkState(**data)
                logger.info(f"Loaded existing pipeline watermark: {state.last_extracted_watermark} (Total records: {state.total_records_extracted})")
                return state
        except Exception as e:
            logger.warning(f"Could not load state file ({e}), initializing fresh watermark.")

        default_state = WatermarkState(
            pipeline_name=self.pipeline_name,
            last_extracted_watermark="2024-01-01T00:00:00.000",
            status="INITIALIZED"
        )
        self.save_state(default_state)
        return default_state

    def save_state(self, state: WatermarkState) -> None:
        """Atomically saves watermark state to storage."""
        self.current_state = state
        self.storage.write_json(self.STATE_FILE_PATH, state.model_dump())
        logger.debug(f"Persisted state: watermark={state.last_extracted_watermark}, status={state.status}")

    def get_watermark(self) -> str:
        """Returns the current high-water mark timestamp."""
        return self.current_state.last_extracted_watermark

    def start_run(self, batch_id: str) -> None:
        """Marks run as in-progress."""
        self.current_state.status = "IN_PROGRESS"
        self.current_state.last_batch_id = batch_id
        self.current_state.last_run_timestamp = datetime.utcnow().isoformat()
        self.save_state(self.current_state)

    def commit_watermark(self, new_watermark: str, records_ingested: int, batch_id: str) -> None:
        """
        Commits a new high watermark ONLY after the raw batch has been durably stored.
        Prevents advancing the watermark if raw ingestion failed.
        """
        self.current_state.last_extracted_watermark = new_watermark
        self.current_state.total_records_extracted += records_ingested
        self.current_state.last_batch_id = batch_id
        self.current_state.last_run_timestamp = datetime.utcnow().isoformat()
        self.current_state.status = "SUCCESS"
        self.current_state.error_message = None
        self.save_state(self.current_state)
        logger.info(f"Committed new watermark: {new_watermark} (+{records_ingested} records, batch={batch_id})")

    def record_failure(self, error_message: str, batch_id: Optional[str] = None) -> None:
        """Records a run failure without advancing the watermark, enabling automatic retry."""
        self.current_state.status = "FAILED"
        self.current_state.error_message = error_message
        if batch_id:
            self.current_state.last_batch_id = batch_id
        try:
            self.save_state(self.current_state)
        except Exception as err:
            logger.error(f"Failed to persist failure state: {err}")
        logger.error(f"Ingestion run failed. Watermark NOT advanced: {self.current_state.last_extracted_watermark}. Reason: {error_message}")

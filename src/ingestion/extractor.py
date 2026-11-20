"""
Ingestion Extractor and Pipeline Recovery Engine
Coordinates API calls, watermark-based incremental extraction, immutable raw landing, and crash recovery.
"""

import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from config.settings import settings
from config.logging_config import logger
from src.common.storage import StorageBackend
from src.common.state_manager import StateManager
from src.ingestion.client import Chicago311Client
from src.ingestion.mock_generator import Chicago311MockGenerator


class IngestionExtractor:
    """
    Orchestrates raw data ingestion into immutable partitioned storage.
    """

    def __init__(self, storage: StorageBackend, state_manager: StateManager):
        self.storage = storage
        self.state_manager = state_manager
        self.client = Chicago311Client(
            endpoint=settings.chicago_311_endpoint,
            app_token=settings.socrata_app_token,
            batch_size=settings.ingestion_batch_size,
            rate_limit_delay=settings.ingestion_rate_limit_delay
        )

    def _persist_raw_batch(self, batch: List[Dict[str, Any]], batch_id: str) -> str:
        """
        Stores raw batch as an immutable JSON snapshot partitioned by ingestion date.
        Format: raw/year=YYYY/month=MM/day=DD/batch_{timestamp}_{batch_id}.json
        """
        now = datetime.utcnow()
        partition_path = f"raw/year={now.year:04d}/month={now.month:02d}/day={now.day:02d}/batch_{now.strftime('%Y%m%d_%H%M%S')}_{batch_id}.json"
        
        envelope = {
            "batch_id": batch_id,
            "ingested_at": now.isoformat(),
            "record_count": len(batch),
            "records": batch
        }
        persisted_path = self.storage.write_json(partition_path, envelope)
        logger.info(f"Persisted immutable raw snapshot: {persisted_path} ({len(batch)} records)")
        return persisted_path

    def run_incremental(
        self,
        mode: str = "live",
        max_records: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes an incremental extraction run from the current watermark.
        """
        batch_id = str(uuid.uuid4())[:8]
        current_watermark = self.state_manager.get_watermark()
        self.state_manager.start_run(batch_id)

        logger.info(f"Starting incremental run [Batch: {batch_id}] from watermark: {current_watermark} (Mode: {mode})")
        total_extracted = 0
        persisted_files = []
        highest_watermark = current_watermark

        try:
            if mode == "live":
                page_generator = self.client.extract_incremental(
                    watermark=current_watermark,
                    max_records=max_records
                )
            else:
                # Mock simulation mode
                simulated = Chicago311MockGenerator.generate_batch(
                    count=max_records or 300,
                    inject_invalid=True
                )
                page_generator = [simulated]

            for page in page_generator:
                if not page:
                    continue

                persisted_path = self._persist_raw_batch(page, batch_id)
                persisted_files.append(persisted_path)
                total_extracted += len(page)

                # Scan batch for highest last_modified_date
                for rec in page:
                    mod_date = rec.get("last_modified_date") or rec.get("updated_date") or rec.get("created_date")
                    if mod_date and str(mod_date) > str(highest_watermark):
                        highest_watermark = str(mod_date)

            # Atomic commit of new watermark ONLY after durable disk/GCS write
            if total_extracted > 0 and highest_watermark > current_watermark:
                self.state_manager.commit_watermark(
                    new_watermark=highest_watermark,
                    records_ingested=total_extracted,
                    batch_id=batch_id
                )
            else:
                self.state_manager.commit_watermark(
                    new_watermark=current_watermark,
                    records_ingested=0,
                    batch_id=batch_id
                )
                logger.info("No newer records found since last watermark.")

            return {
                "batch_id": batch_id,
                "status": "SUCCESS",
                "records_extracted": total_extracted,
                "prior_watermark": current_watermark,
                "new_watermark": highest_watermark,
                "persisted_files": persisted_files
            }

        except Exception as e:
            logger.exception(f"Ingestion run failed abruptly: {e}")
            self.state_manager.record_failure(error_message=str(e), batch_id=batch_id)
            raise

    def run_backfill(
        self,
        start_date: str,
        end_date: str,
        mode: str = "live",
        max_records: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes a historical backfill for an isolated date range without modifying the forward-moving production watermark.
        """
        batch_id = f"backfill_{str(uuid.uuid4())[:8]}"
        logger.info(f"Starting historical backfill [Batch: {batch_id}] range: [{start_date} to {end_date}]")
        total_extracted = 0
        persisted_files = []

        try:
            if mode == "live":
                page_generator = self.client.extract_backfill(
                    start_date=start_date,
                    end_date=end_date,
                    max_records=max_records
                )
            else:
                from datetime import datetime as dt
                s_dt = dt.fromisoformat(start_date.replace("Z", "+00:00").split("+")[0])
                simulated = Chicago311MockGenerator.generate_batch(
                    count=max_records or 250,
                    start_date=s_dt,
                    inject_invalid=False
                )
                page_generator = [simulated]

            for page in page_generator:
                if not page:
                    continue
                persisted_path = self._persist_raw_batch(page, batch_id)
                persisted_files.append(persisted_path)
                total_extracted += len(page)

            logger.info(f"Backfill batch {batch_id} completed. Extracted {total_extracted} records. Forward watermark unchanged.")
            return {
                "batch_id": batch_id,
                "status": "SUCCESS",
                "records_extracted": total_extracted,
                "start_date": start_date,
                "end_date": end_date,
                "persisted_files": persisted_files
            }

        except Exception as e:
            logger.exception(f"Backfill run failed: {e}")
            raise

"""
Chicago Open Data (Socrata Open311) API Client
Extracts public infrastructure service requests using incremental watermarking or backfill windows.
"""

from typing import Dict, Any, Generator, List, Optional
from config.settings import settings
from config.logging_config import logger
from src.ingestion.paginator import APIPaginator


class Chicago311Client:
    """
    Socrata Open Data (SODA) client for the Chicago 311 Service Requests dataset.
    Dataset ID: v6vf-nfxy
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        app_token: Optional[str] = None,
        batch_size: int = 2000,
        rate_limit_delay: float = 0.2
    ):
        self.endpoint = endpoint or settings.chicago_311_endpoint
        self.app_token = app_token or settings.socrata_app_token
        self.paginator = APIPaginator(
            batch_size=batch_size,
            max_retries=settings.ingestion_max_retries,
            backoff_factor=settings.ingestion_backoff_factor,
            rate_limit_delay=rate_limit_delay
        )

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.app_token:
            headers["X-App-Token"] = self.app_token
        return headers

    def extract_incremental(
        self,
        watermark: str,
        max_records: Optional[int] = None
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Extracts records modified strictly after the given high-water mark timestamp.
        Orders by last_modified_date ASC so progress can be safely checkpointed batch-by-batch.
        """
        logger.info(f"Initiating incremental extraction for records modified after: {watermark}")
        base_params = {
            "$where": f"last_modified_date > '{watermark}'",
            "$order": "last_modified_date ASC"
        }
        yield from self.paginator.paginate(
            url=self.endpoint,
            base_params=base_params,
            headers=self._get_headers(),
            max_records=max_records
        )

    def extract_backfill(
        self,
        start_date: str,
        end_date: str,
        max_records: Optional[int] = None
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Extracts historical slice of data between start_date and end_date.
        """
        logger.info(f"Initiating backfill extraction window: [{start_date} TO {end_date}]")
        base_params = {
            "$where": f"last_modified_date >= '{start_date}' AND last_modified_date <= '{end_date}'",
            "$order": "last_modified_date ASC"
        }
        yield from self.paginator.paginate(
            url=self.endpoint,
            base_params=base_params,
            headers=self._get_headers(),
            max_records=max_records
        )

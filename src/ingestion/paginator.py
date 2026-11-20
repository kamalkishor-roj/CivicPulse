"""
API Paginator and Rate Limiting Engine
Implements offset/cursor pagination, exponential backoff, and adaptive rate throttling.
"""

import time
import random
from typing import Dict, Any, Generator, List, Optional
import requests
from config.logging_config import logger


class APIPaginator:
    """
    Handles paginated requests to REST APIs with exponential backoff and rate limit handling.
    """

    def __init__(
        self,
        batch_size: int = 2000,
        max_retries: int = 5,
        backoff_factor: float = 2.0,
        rate_limit_delay: float = 0.2
    ):
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.rate_limit_delay = rate_limit_delay

    def fetch_with_retry(
        self,
        url: str,
        params: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Executes a GET request with exponential backoff on transient errors (429, 5xx).
        """
        retries = 0
        while retries <= self.max_retries:
            try:
                # Polite rate-limiting between successive calls
                if self.rate_limit_delay > 0:
                    time.sleep(self.rate_limit_delay)

                response = requests.get(url, params=params, headers=headers or {}, timeout=timeout)

                # Handle rate limit (429) or server error (5xx)
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    retries += 1
                    sleep_time = (self.backoff_factor ** retries) + random.uniform(0.1, 1.0)
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        sleep_time = max(sleep_time, float(retry_after))

                    logger.warning(
                        f"HTTP {response.status_code} received from {url}. "
                        f"Retrying in {sleep_time:.2f}s (Attempt {retries}/{self.max_retries})..."
                    )
                    time.sleep(sleep_time)
                    continue

                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    logger.error(f"Unexpected response structure: {type(data)}")
                    return []
                return data

            except (requests.exceptions.RequestException, requests.exceptions.Timeout) as err:
                retries += 1
                if retries > self.max_retries:
                    logger.error(f"Exceeded max retries ({self.max_retries}) for {url}: {err}")
                    raise
                sleep_time = (self.backoff_factor ** retries) + random.uniform(0.1, 0.5)
                logger.warning(f"Network error: {err}. Retrying in {sleep_time:.2f}s (Attempt {retries}/{self.max_retries})...")
                time.sleep(sleep_time)

        raise RuntimeError(f"Failed to fetch data from {url} after {self.max_retries} attempts.")

    def paginate(
        self,
        url: str,
        base_params: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        max_records: Optional[int] = None
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Yields pages of records until all available records are consumed or max_records is reached.
        """
        offset = 0
        records_yielded = 0

        while True:
            params = dict(base_params)
            params["$limit"] = self.batch_size
            params["$offset"] = offset

            logger.info(f"Fetching page: offset={offset}, limit={self.batch_size}")
            batch = self.fetch_with_retry(url, params=params, headers=headers)

            if not batch:
                logger.info("No further records returned by endpoint. Pagination complete.")
                break

            yield batch

            batch_count = len(batch)
            records_yielded += batch_count
            offset += batch_count

            if max_records and records_yielded >= max_records:
                logger.info(f"Reached requested max_records threshold: {records_yielded}/{max_records}")
                break

            # If fewer records returned than batch_size, we reached the end of the query result
            if batch_count < self.batch_size:
                logger.info(f"Final page reached (returned {batch_count} < {self.batch_size}). Pagination complete.")
                break

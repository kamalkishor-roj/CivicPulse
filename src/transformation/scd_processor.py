"""
SCD Type 2 (Slowly Changing Dimension Type 2) Status History Engine
Maintains immutable chronological status lifecycle intervals, handles late-arriving data,
and computes duration in each status.
"""

import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from config.logging_config import logger
from src.common.models import StatusHistoryRecord


class SCDType2Processor:
    """
    Manages SCD Type 2 historical status tracking for 311 Service Requests.
    """

    @staticmethod
    def _parse_dt(val: Any) -> datetime:
        if isinstance(val, datetime):
            return val
        clean = str(val).replace("Z", "+00:00").split("+")[0]
        if "." in clean:
            parts = clean.split(".")
            parts[1] = parts[1][:6]
            clean = ".".join(parts)
        return datetime.fromisoformat(clean)

    @classmethod
    def generate_surrogate_key(cls, request_id: str, status: str, start_date: datetime) -> str:
        """
        Generates deterministic MD5 surrogate key for dim_service_request_status_history.
        """
        raw = f"{request_id}_{status.strip().lower()}_{start_date.isoformat()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @classmethod
    def build_timeline_from_events(
        cls,
        request_id: str,
        events: List[Dict[str, Any]]
    ) -> List[StatusHistoryRecord]:
        """
        Constructs a complete, clean SCD Type 2 timeline given a list of raw event snapshots.
        Handles out-of-order / late-arriving events by chronological sorting.
        """
        if not events:
            return []

        # Extract distinct status changes sorted by modification date
        parsed_events = []
        for e in events:
            st = str(e.get("status", "")).strip().title()
            dt_val = e.get("last_modified_date") or e.get("updated_date") or e.get("created_date")
            if st and dt_val:
                parsed_events.append((cls._parse_dt(dt_val), st))

        # Sort chronologically (handles late-arriving records)
        parsed_events.sort(key=lambda x: x[0])

        # Deduplicate consecutive identical statuses (e.g. Open -> Open -> In Progress)
        deduped_events = []
        last_status = None
        for dt_val, status in parsed_events:
            if status != last_status:
                deduped_events.append((dt_val, status))
                last_status = status

        if not deduped_events:
            return []

        history_records: List[StatusHistoryRecord] = []
        for i, (dt_start, status) in enumerate(deduped_events):
            version = i + 1
            sk = cls.generate_surrogate_key(request_id, status, dt_start)

            if i < len(deduped_events) - 1:
                # Closed interval
                dt_end = deduped_events[i + 1][0]
                duration_hours = max(0.0, round((dt_end - dt_start).total_seconds() / 3600.0, 2))
                is_current = False
            else:
                # Active / Current interval
                dt_end = None
                duration_hours = None
                is_current = True

            record = StatusHistoryRecord(
                status_history_sk=sk,
                service_request_id=request_id,
                status=status,
                effective_start_date=dt_start,
                effective_end_date=dt_end,
                is_current=is_current,
                version=version,
                duration_in_status_hours=duration_hours,
                status_sequence_order=version
            )
            history_records.append(record)

        return history_records

    @classmethod
    def apply_scd2_update(
        cls,
        existing_history: List[Dict[str, Any]],
        incoming_record: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Merges an incoming record into an existing SCD2 history timeline.
        Idempotent and resilient to out-of-order updates.
        """
        req_id = incoming_record.get("sr_number") or incoming_record.get("service_request_id")
        if not req_id:
            return existing_history

        # Convert existing history back to event tuples
        events = []
        for h in existing_history:
            events.append({
                "status": h["status"],
                "last_modified_date": h["effective_start_date"]
            })

        # Add incoming event
        incoming_status = incoming_record.get("status")
        incoming_date = incoming_record.get("last_modified_date") or incoming_record.get("created_date")
        if incoming_status and incoming_date:
            events.append({
                "status": incoming_status,
                "last_modified_date": incoming_date
            })

        new_timeline = cls.build_timeline_from_events(req_id, events)
        return [rec.model_dump() for rec in new_timeline]

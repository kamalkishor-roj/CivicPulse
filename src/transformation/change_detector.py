"""
Change Detection and Deduplication Engine
Detects attribute mutations, status transitions, reassignments, and complaint reopenings.
"""

import hashlib
import json
from typing import Dict, Any, Optional, Tuple


class ChangeDetector:
    """
    Computes deterministic record fingerprints and identifies lifecycle mutations.
    """

    CORE_MUTABLE_FIELDS = [
        "status",
        "owner_department",
        "agency_responsible",
        "street_address",
        "zip_code",
        "latitude",
        "longitude",
        "closed_date"
    ]

    @classmethod
    def compute_record_hash(cls, record: Dict[str, Any]) -> str:
        """
        Generates a deterministic SHA-256 hash across mutable operational fields.
        """
        payload = {}
        for field in cls.CORE_MUTABLE_FIELDS:
            val = record.get(field)
            payload[field] = str(val).strip().lower() if val is not None else ""

        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def detect_changes(
        cls,
        previous_record: Optional[Dict[str, Any]],
        incoming_record: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Compares incoming record with previously known state.
        Returns: (has_changed, change_metadata)
        """
        incoming_hash = cls.compute_record_hash(incoming_record)

        if not previous_record:
            return True, {
                "is_new": True,
                "status_changed": True,
                "agency_reassigned": False,
                "is_reopened": False,
                "record_hash": incoming_hash
            }

        prev_hash = previous_record.get("record_hash") or cls.compute_record_hash(previous_record)

        if incoming_hash == prev_hash:
            # Exact duplicate update (common in Socrata API polling)
            return False, {
                "is_new": False,
                "is_duplicate": True,
                "status_changed": False,
                "agency_reassigned": False,
                "is_reopened": False,
                "record_hash": incoming_hash
            }

        # Status change check
        prev_status = str(previous_record.get("status", "")).strip().lower()
        new_status = str(incoming_record.get("status", "")).strip().lower()
        status_changed = (prev_status != new_status)

        # Reopening detection: Previously resolved/completed, now open/in progress
        was_closed = prev_status in {"completed", "closed"}
        now_active = new_status in {"open", "in progress"}
        is_reopened = was_closed and now_active

        # Agency reassignment
        prev_agency = str(previous_record.get("owner_department") or previous_record.get("agency", "")).strip().lower()
        new_agency = str(incoming_record.get("owner_department") or incoming_record.get("agency", "")).strip().lower()
        agency_reassigned = (prev_agency != new_agency) and bool(prev_agency and new_agency)

        return True, {
            "is_new": False,
            "status_changed": status_changed,
            "agency_reassigned": agency_reassigned,
            "is_reopened": is_reopened,
            "previous_status": prev_status,
            "new_status": new_status,
            "record_hash": incoming_hash
        }

"""
Data Quality Validation and Quarantine (DLQ) Engine
Evaluates structural integrity, temporal logic, and geospatial boundary constraints.
"""

from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from config.settings import settings
from config.logging_config import logger
from src.common.models import QuarantinedRecord
from src.common.storage import StorageBackend


class DataQualityValidator:
    """
    Validates service request records against municipal operational integrity rules.
    """

    VALID_STATUSES = {"open", "in progress", "completed", "closed", "cancelled", "duplicate"}

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    @staticmethod
    def _parse_iso(date_str: Optional[Any]) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            clean = str(date_str).replace("Z", "+00:00").split("+")[0]
            if "." in clean:
                # Truncate fractional seconds to 6 digits if longer
                parts = clean.split(".")
                parts[1] = parts[1][:6]
                clean = ".".join(parts)
            return datetime.fromisoformat(clean)
        except Exception:
            return None

    def validate_record(self, raw: Dict[str, Any]) -> Tuple[bool, List[str], Optional[str]]:
        """
        Validates an individual record.
        Returns: (is_valid, list_of_failed_rules, primary_rejection_reason)
        """
        failed_rules = []

        # Rule 1: Mandatory Identifiers
        req_id = raw.get("sr_number") or raw.get("service_request_id")
        if not req_id or str(req_id).strip() == "" or str(req_id).lower() == "none":
            failed_rules.append("RULE_01_MISSING_PRIMARY_KEY: Record lacks a service_request_id/sr_number")

        req_type = raw.get("sr_type") or raw.get("type_of_service_request")
        if not req_type or str(req_type).strip() == "":
            failed_rules.append("RULE_02_MISSING_TYPE: Record lacks a service request type")

        # Rule 2: Status Domain Check
        status = raw.get("status")
        if not status or str(status).strip() == "":
            failed_rules.append("RULE_03_MISSING_STATUS: Status field is missing or null")
        elif str(status).strip().lower() not in self.VALID_STATUSES:
            failed_rules.append(f"RULE_04_INVALID_STATUS_DOMAIN: Unknown status '{status}'")

        # Rule 3: Temporal Consistency Checks
        created_dt = self._parse_iso(raw.get("created_date"))
        if not created_dt:
            failed_rules.append("RULE_05_INVALID_CREATED_DATE: created_date missing or unparseable")

        modified_dt = self._parse_iso(raw.get("last_modified_date") or raw.get("updated_date"))
        closed_dt = self._parse_iso(raw.get("closed_date"))

        if created_dt and closed_dt:
            if closed_dt < created_dt:
                failed_rules.append(
                    f"RULE_06_TEMPORAL_PARADOX: closed_date ({closed_dt}) cannot be earlier than created_date ({created_dt})"
                )

        # Rule 4: Geospatial Bounding Box (Chicago City Limits)
        lat = raw.get("latitude")
        lon = raw.get("longitude")
        if lat is not None and lon is not None:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                # Ignore (0,0) or null coordinates if location not yet captured
                if not (lat_f == 0.0 and lon_f == 0.0):
                    if not (settings.chicago_min_lat <= lat_f <= settings.chicago_max_lat):
                        failed_rules.append(
                            f"RULE_07_GEO_BOUNDS_LAT: Latitude {lat_f} outside Chicago bounds [{settings.chicago_min_lat}, {settings.chicago_max_lat}]"
                        )
                    if not (settings.chicago_min_lon <= lon_f <= settings.chicago_max_lon):
                        failed_rules.append(
                            f"RULE_08_GEO_BOUNDS_LON: Longitude {lon_f} outside Chicago bounds [{settings.chicago_min_lon}, {settings.chicago_max_lon}]"
                        )
            except (ValueError, TypeError):
                failed_rules.append(f"RULE_09_CORRUPTED_COORDINATES: Non-numeric latitude/longitude ({lat}, {lon})")

        is_valid = len(failed_rules) == 0
        primary_reason = failed_rules[0] if failed_rules else None
        return is_valid, failed_rules, primary_reason

    def partition_and_quarantine(
        self,
        records: List[Dict[str, Any]],
        batch_id: str
    ) -> Tuple[List[Dict[str, Any]], List[QuarantinedRecord]]:
        """
        Splits incoming records into valid records for Silver processing
        and quarantined records for Dead-Letter Queue (DLQ).
        """
        valid_records = []
        quarantined = []

        for rec in records:
            is_valid, failures, reason = self.validate_record(rec)
            if is_valid:
                valid_records.append(rec)
            else:
                q_item = QuarantinedRecord(
                    service_request_id=rec.get("sr_number") or rec.get("service_request_id"),
                    raw_payload=rec,
                    failed_rules=failures,
                    rejection_reason=reason or "Validation failure",
                    source_batch_id=batch_id
                )
                quarantined.append(q_item)

        if quarantined:
            now = datetime.utcnow()
            q_path = f"quarantine/year={now.year:04d}/month={now.month:02d}/day={now.day:02d}/quarantine_{now.strftime('%Y%m%d_%H%M%S')}_{batch_id}.json"
            self.storage.write_json(q_path, [q.model_dump() for q in quarantined])
            logger.warning(f"Quarantined {len(quarantined)} invalid records to: {q_path}")

        logger.info(f"Data Quality Validation: {len(valid_records)} passed, {len(quarantined)} quarantined (Batch {batch_id})")
        return valid_records, quarantined

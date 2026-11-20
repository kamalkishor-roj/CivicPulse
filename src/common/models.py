"""
Data Models and Schemas for CivicPulse
Provides Pydantic models for raw ingestion, silver entities, SCD Type 2 tracking, and quarantine.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict, field_validator


class ServiceRequestRaw(BaseModel):
    """
    Raw ingestion model representing an incoming record from the Chicago Open311 / Socrata API.
    Uses extra='allow' to support Schema Evolution seamlessly when the municipality adds new attributes.
    """
    model_config = ConfigDict(extra="allow")

    sr_number: Optional[str] = Field(default=None, alias="sr_number")
    service_request_id: Optional[str] = Field(default=None, alias="service_request_id")
    sr_type: Optional[str] = Field(default=None, alias="sr_type")
    type_of_service_request: Optional[str] = Field(default=None, alias="type_of_service_request")
    sr_short_code: Optional[str] = Field(default=None, alias="sr_short_code")
    owner_department: Optional[str] = Field(default=None, alias="owner_department")
    agency_responsible: Optional[str] = Field(default=None, alias="agency_responsible")
    status: Optional[str] = Field(default=None, alias="status")
    created_date: Optional[str] = Field(default=None, alias="created_date")
    last_modified_date: Optional[str] = Field(default=None, alias="last_modified_date")
    closed_date: Optional[str] = Field(default=None, alias="closed_date")
    street_address: Optional[str] = Field(default=None, alias="street_address")
    zip_code: Optional[str] = Field(default=None, alias="zip_code")
    ward: Optional[Any] = Field(default=None, alias="ward")
    community_area: Optional[Any] = Field(default=None, alias="community_area")
    police_district: Optional[Any] = Field(default=None, alias="police_district")
    latitude: Optional[Any] = Field(default=None, alias="latitude")
    longitude: Optional[Any] = Field(default=None, alias="longitude")
    location: Optional[Any] = Field(default=None, alias="location")
    duplicate: Optional[Any] = Field(default=False, alias="duplicate")
    legacy_record: Optional[Any] = Field(default=False, alias="legacy_record")

    def get_id(self) -> Optional[str]:
        """Resolves ID across Socrata and Open311 field naming variations."""
        return self.sr_number or self.service_request_id

    def get_type(self) -> Optional[str]:
        """Resolves request type across field naming variations."""
        return self.sr_type or self.type_of_service_request

    def get_agency(self) -> str:
        """Resolves department/agency name."""
        return self.owner_department or self.agency_responsible or "Unknown Department"


class ServiceRequestCleaned(BaseModel):
    """
    Standardized Silver layer representation of a Service Request.
    """
    service_request_id: str
    sr_type: str
    sr_short_code: Optional[str] = None
    agency: str
    status: str
    created_date: datetime
    last_modified_date: datetime
    closed_date: Optional[datetime] = None
    resolution_time_hours: Optional[float] = None
    street_address: Optional[str] = None
    zip_code: Optional[str] = None
    ward: Optional[int] = None
    community_area: Optional[int] = None
    police_district: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_duplicate: bool = False
    is_reopened: bool = False
    record_hash: str
    extended_attributes: Dict[str, Any] = Field(default_factory=dict)
    ingestion_timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_batch_id: str


class StatusHistoryRecord(BaseModel):
    """
    SCD Type 2 (Slowly Changing Dimension Type 2) Status History Record.
    Tracks every status transition over the lifecycle of a complaint.
    """
    status_history_sk: str  # MD5 / SHA256 surrogate key
    service_request_id: str
    status: str
    effective_start_date: datetime
    effective_end_date: Optional[datetime] = None  # None or 9999-12-31 indicates current
    is_current: bool = True
    version: int = 1
    duration_in_status_hours: Optional[float] = None
    status_sequence_order: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QuarantinedRecord(BaseModel):
    """
    Dead-Letter Queue (DLQ) record for validation failures.
    """
    service_request_id: Optional[str] = None
    raw_payload: Dict[str, Any]
    failed_rules: List[str]
    rejection_reason: str
    quarantined_at: datetime = Field(default_factory=datetime.utcnow)
    source_batch_id: str


class WatermarkState(BaseModel):
    """
    Persistent pipeline watermark state to guarantee idempotent ingestion and resume after failures.
    """
    pipeline_name: str = "civicpulse_311_ingestion"
    last_extracted_watermark: str = "2020-01-01T00:00:00.000"
    last_run_timestamp: Optional[str] = None
    total_records_extracted: int = 0
    last_batch_id: Optional[str] = None
    status: str = "INITIALIZED"  # INITIALIZED, IN_PROGRESS, SUCCESS, FAILED
    error_message: Optional[str] = None

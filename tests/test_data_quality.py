"""
Unit Tests for Data Quality Rules and Quarantine (DLQ)
"""

from src.transformation.quality import DataQualityValidator


def test_valid_record_passes(storage, sample_valid_records):
    validator = DataQualityValidator(storage=storage)
    for rec in sample_valid_records:
        is_valid, failures, reason = validator.validate_record(rec)
        assert is_valid is True
        assert len(failures) == 0
        assert reason is None


def test_missing_primary_key_quarantine(storage):
    validator = DataQualityValidator(storage=storage)
    bad_rec = {
        "sr_number": None,
        "sr_type": "Pothole in Street Complaint",
        "status": "Open",
        "created_date": "2024-06-01T10:00:00.000"
    }
    is_valid, failures, reason = validator.validate_record(bad_rec)
    assert is_valid is False
    assert any("RULE_01_MISSING_PRIMARY_KEY" in f for f in failures)


def test_temporal_paradox_quarantine(storage):
    """closed_date cannot be earlier than created_date."""
    validator = DataQualityValidator(storage=storage)
    bad_rec = {
        "sr_number": "SR-ERR-01",
        "sr_type": "Pothole in Street Complaint",
        "status": "Completed",
        "created_date": "2024-06-10T12:00:00.000",
        "closed_date": "2024-06-05T12:00:00.000"  # 5 days prior to creation!
    }
    is_valid, failures, reason = validator.validate_record(bad_rec)
    assert is_valid is False
    assert any("RULE_06_TEMPORAL_PARADOX" in f for f in failures)


def test_out_of_bounds_geocoordinates(storage):
    """Coordinates outside Chicago city bounds must be rejected."""
    validator = DataQualityValidator(storage=storage)
    bad_rec = {
        "sr_number": "SR-ERR-02",
        "sr_type": "Pothole in Street Complaint",
        "status": "Open",
        "created_date": "2024-06-10T12:00:00.000",
        "latitude": 34.0522,  # Los Angeles, CA
        "longitude": -118.2437
    }
    is_valid, failures, reason = validator.validate_record(bad_rec)
    assert is_valid is False
    assert any("RULE_07_GEO_BOUNDS_LAT" in f for f in failures)
    assert any("RULE_08_GEO_BOUNDS_LON" in f for f in failures)


def test_partition_and_quarantine_dlq(storage, sample_valid_records):
    validator = DataQualityValidator(storage=storage)
    mixed_records = list(sample_valid_records) + [
        {"sr_number": None, "sr_type": "Bad", "status": "Open", "created_date": "2024-01-01T00:00:00"}
    ]

    valid, quarantined = validator.partition_and_quarantine(mixed_records, batch_id="test_b99")
    assert len(valid) == len(sample_valid_records)
    assert len(quarantined) == 1
    assert "RULE_01_MISSING_PRIMARY_KEY" in quarantined[0].failed_rules[0]

    # Verify quarantine file was persisted to DLQ storage
    q_files = storage.list_files("quarantine", suffix=".json")
    assert len(q_files) > 0

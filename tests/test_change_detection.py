"""
Unit Tests for Change Detection and Record Hashing
"""

from src.transformation.change_detector import ChangeDetector


def test_identical_record_hash():
    rec1 = {
        "status": "Open",
        "owner_department": "CDOT",
        "street_address": "123 Main St",
        "latitude": 41.8781,
        "longitude": -87.6298
    }
    rec2 = dict(rec1)
    # Different case or trailing spaces should resolve identically
    rec2["status"] = " open "

    h1 = ChangeDetector.compute_record_hash(rec1)
    h2 = ChangeDetector.compute_record_hash(rec2)
    assert h1 == h2


def test_status_mutation_detection():
    prev = {"status": "Open", "owner_department": "CDOT"}
    curr = {"status": "In Progress", "owner_department": "CDOT"}

    has_changed, meta = ChangeDetector.detect_changes(prev, curr)
    assert has_changed is True
    assert meta["status_changed"] is True
    assert meta["is_duplicate"] is False if "is_duplicate" in meta else True


def test_reopen_detection():
    prev = {"status": "Completed", "owner_department": "CDOT"}
    curr = {"status": "Open", "owner_department": "CDOT"}

    has_changed, meta = ChangeDetector.detect_changes(prev, curr)
    assert has_changed is True
    assert meta["is_reopened"] is True

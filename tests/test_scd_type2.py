"""
Unit Tests for SCD Type 2 Status History Engine
"""

from datetime import datetime, timedelta
from src.transformation.scd_processor import SCDType2Processor


def test_standard_incident_lifecycle():
    """
    Verifies the exact scenario from the project brief:
    Request ID 101:
      Day 1: Open
      Day 2: In Progress
      Day 5: Completed
    """
    req_id = "101"
    day1 = datetime(2024, 5, 1, 9, 0, 0)
    day2 = datetime(2024, 5, 2, 9, 0, 0)  # +24 hours
    day5 = datetime(2024, 5, 5, 9, 0, 0)  # +72 hours

    events = [
        {"status": "Open", "last_modified_date": day1.isoformat()},
        {"status": "In Progress", "last_modified_date": day2.isoformat()},
        {"status": "Completed", "last_modified_date": day5.isoformat()}
    ]

    timeline = SCDType2Processor.build_timeline_from_events(req_id, events)

    assert len(timeline) == 3

    # Version 1: Open
    v1 = timeline[0]
    assert v1.version == 1
    assert v1.status == "Open"
    assert v1.effective_start_date == day1
    assert v1.effective_end_date == day2
    assert v1.is_current is False
    assert v1.duration_in_status_hours == 24.0

    # Version 2: In Progress
    v2 = timeline[1]
    assert v2.version == 2
    assert v2.status == "In Progress"
    assert v2.effective_start_date == day2
    assert v2.effective_end_date == day5
    assert v2.is_current is False
    assert v2.duration_in_status_hours == 72.0

    # Version 3: Completed (Current active state)
    v3 = timeline[2]
    assert v3.version == 3
    assert v3.status == "Completed"
    assert v3.effective_start_date == day5
    assert v3.effective_end_date is None
    assert v3.is_current is True
    assert v3.duration_in_status_hours is None


def test_late_arriving_data_handling():
    """
    CRITICAL INTERVIEW REQUIREMENT:
    Verify that out-of-order / late-arriving events are correctly integrated
    into the SCD2 timeline chronologically rather than appended incorrectly.
    """
    req_id = "202"
    day1 = datetime(2024, 6, 1, 10, 0, 0)
    day2 = datetime(2024, 6, 2, 10, 0, 0)
    day4 = datetime(2024, 6, 4, 10, 0, 0)

    # Ingestion stream arrives out of order: Day 4 arrives BEFORE Day 2
    out_of_order_events = [
        {"status": "Completed", "last_modified_date": day4.isoformat()},
        {"status": "Open", "last_modified_date": day1.isoformat()},
        {"status": "In Progress", "last_modified_date": day2.isoformat()},  # Late-arriving event!
    ]

    timeline = SCDType2Processor.build_timeline_from_events(req_id, out_of_order_events)

    assert len(timeline) == 3
    # Chronological integrity must be restored
    assert timeline[0].status == "Open"
    assert timeline[0].version == 1
    assert timeline[1].status == "In Progress"
    assert timeline[1].version == 2
    assert timeline[2].status == "Completed"
    assert timeline[2].version == 3
    assert timeline[2].is_current is True


def test_reopened_complaint_lifecycle():
    """
    Verifies that a reopened complaint (Completed -> Open) creates a new active version
    while closing the previous Completed interval.
    """
    req_id = "303"
    t1 = datetime(2024, 7, 1, 12, 0, 0)
    t2 = datetime(2024, 7, 3, 12, 0, 0)  # Completed
    t3 = datetime(2024, 7, 6, 12, 0, 0)  # Citizen reopens

    events = [
        {"status": "Open", "last_modified_date": t1.isoformat()},
        {"status": "Completed", "last_modified_date": t2.isoformat()},
        {"status": "Open", "last_modified_date": t3.isoformat()},
    ]

    timeline = SCDType2Processor.build_timeline_from_events(req_id, events)

    assert len(timeline) == 3
    assert timeline[1].status == "Completed"
    assert timeline[1].is_current is False
    assert timeline[1].effective_end_date == t3

    # New reopened row
    assert timeline[2].status == "Open"
    assert timeline[2].version == 3
    assert timeline[2].is_current is True
    assert timeline[2].effective_start_date == t3

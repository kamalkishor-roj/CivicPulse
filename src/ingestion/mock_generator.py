"""
Chicago 311 Operational Data Generator
Generates realistic multi-stage service request records for testing lifecycles,
SCD Type 2 transitions, late-arriving events, schema evolution, and quarantine logic.
"""

import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

CATEGORIES = [
    {"type": "Pothole in Street Complaint", "code": "PHF", "agency": "CDOT - Department of Transportation", "sla_days": 6},
    {"type": "Garbage Cart Maintenance", "code": "SRO", "agency": "Streets and Sanitation", "sla_days": 5},
    {"type": "Water in Basement", "code": "WIB", "agency": "DWM - Department of Water Management", "sla_days": 3},
    {"type": "Street Light 1 Out", "code": "SLO", "agency": "CDOT - Department of Transportation", "sla_days": 7},
    {"type": "Street Lights - All Out", "code": "SLA", "agency": "CDOT - Department of Transportation", "sla_days": 2},
    {"type": "Drainage / Clogged Catch Basin", "code": "DRAIN", "agency": "DWM - Department of Water Management", "sla_days": 4},
    {"type": "Fly Dumping / Illegal Dumping", "code": "FLY", "agency": "Streets and Sanitation", "sla_days": 4},
    {"type": "Graffiti Removal", "code": "GRAF", "agency": "Streets and Sanitation", "sla_days": 3},
    {"type": "Tree Debris / Branch Down", "code": "TREE", "agency": "Streets and Sanitation", "sla_days": 5},
    {"type": "Abandoned Vehicle Complaint", "code": "VEH", "agency": "Streets and Sanitation", "sla_days": 14},
]

CHICAGO_STREETS = [
    "4700 S MICHIGAN AVE", "1200 N ASHLAND AVE", "3500 W BELMONT AVE",
    "200 E RANDOLPH ST", "6300 S HALSTED ST", "7900 S COTTAGE GROVE AVE",
    "1600 W DIVISION ST", "4300 N PULASKI RD", "5500 S KEDZIE AVE",
    "2400 W DEVON AVE", "7100 S STATE ST", "3100 N CICERO AVE"
]

CHICAGO_ZIPCODES = [
    "60601", "60605", "60611", "60614", "60616", "60618", "60621",
    "60622", "60625", "60629", "60637", "60647", "60649", "60651"
]


class Chicago311MockGenerator:
    """
    Generates synthetic Chicago 311 operational datasets mimicking real city workloads.
    """

    @staticmethod
    def generate_incident_lifecycle(
        request_id: str,
        base_date: datetime,
        category: Dict[str, Any],
        address: str,
        zip_code: str,
        ward: int,
        lat: float,
        lon: float,
        include_reopen: bool = False,
        stage: str = "completed"
    ) -> List[Dict[str, Any]]:
        """
        Generates the complete temporal lifecycle of a single incident.
        Supports stages: 'open', 'in_progress', 'completed' (with optional reopen).
        """
        records = []
        created_str = base_date.strftime("%Y-%m-%dT%H:%M:%S.000")

        # Day 1: Created / Open
        t1 = base_date
        rec1 = {
            "sr_number": request_id,
            "sr_type": category["type"],
            "sr_short_code": category["code"],
            "owner_department": category["agency"],
            "status": "Open",
            "created_date": created_str,
            "last_modified_date": t1.strftime("%Y-%m-%dT%H:%M:%S.000"),
            "closed_date": None,
            "street_address": address,
            "zip_code": zip_code,
            "ward": str(ward),
            "community_area": str(random.randint(1, 77)),
            "police_district": str(random.randint(1, 25)),
            "latitude": str(lat),
            "longitude": str(lon),
            "duplicate": False,
            "legacy_record": False
        }
        records.append(rec1)
        if stage == "open":
            return records

        # Day 2: In Progress
        t2 = base_date + timedelta(days=random.randint(1, 2), hours=random.randint(2, 6))
        rec2 = dict(rec1)
        rec2["status"] = "In Progress"
        rec2["last_modified_date"] = t2.strftime("%Y-%m-%dT%H:%M:%S.000")
        records.append(rec2)
        if stage == "in_progress":
            return records

        # Day 5: Completed
        t3 = t2 + timedelta(days=random.randint(2, 5), hours=random.randint(1, 8))
        rec3 = dict(rec2)
        rec3["status"] = "Completed"
        rec3["closed_date"] = t3.strftime("%Y-%m-%dT%H:%M:%S.000")
        rec3["last_modified_date"] = t3.strftime("%Y-%m-%dT%H:%M:%S.000")
        records.append(rec3)

        # Optional: Reopened scenario (citizen reports issue was not solved or recurred)
        if include_reopen:
            t4 = t3 + timedelta(days=random.randint(1, 3))
            rec4 = dict(rec3)
            rec4["status"] = "Open"  # Reopened
            rec4["closed_date"] = None
            rec4["last_modified_date"] = t4.strftime("%Y-%m-%dT%H:%M:%S.000")
            rec4["citizen_reopen_reason"] = "Pothole filled with loose gravel and washed out during rain"
            records.append(rec4)

            # Half of reopened tickets get resolved again; half remain active in the reopened backlog
            if random.random() < 0.6:
                t5 = t4 + timedelta(days=random.randint(2, 4))
                rec5 = dict(rec4)
                rec5["status"] = "Completed"
                rec5["closed_date"] = t5.strftime("%Y-%m-%dT%H:%M:%S.000")
                rec5["last_modified_date"] = t5.strftime("%Y-%m-%dT%H:%M:%S.000")
                records.append(rec5)

        return records

    @classmethod
    def generate_batch(
        cls,
        count: int = 500,
        start_date: Optional[datetime] = None,
        inject_invalid: bool = True,
        reopen_rate: float = 0.08
    ) -> List[Dict[str, Any]]:
        """
        Generates a collection of realistic service request updates across lifecycles.
        """
        base_time = start_date or (datetime.utcnow() - timedelta(days=30))
        all_records = []
        incident_count = max(count // 3, 50)

        for i in range(1, incident_count + 1):
            req_id = f"SR24-{100000 + i}"
            cat = random.choice(CATEGORIES)
            address = random.choice(CHICAGO_STREETS)
            zip_code = random.choice(CHICAGO_ZIPCODES)
            ward = random.randint(1, 50)
            lat = round(random.uniform(41.65, 42.01), 6)
            lon = round(random.uniform(-87.90, -87.55), 6)
            incident_start = base_time + timedelta(days=random.randint(0, 20), hours=random.randint(0, 23))

            stage_roll = random.random()
            if stage_roll < 0.15:
                stage = "open"
            elif stage_roll < 0.40:
                stage = "in_progress"
            else:
                stage = "completed"

            should_reopen = (stage == "completed" and random.random() < reopen_rate)
            lifecycle = cls.generate_incident_lifecycle(
                request_id=req_id,
                base_date=incident_start,
                category=cat,
                address=address,
                zip_code=zip_code,
                ward=ward,
                lat=lat,
                lon=lon,
                include_reopen=should_reopen,
                stage=stage
            )
            all_records.extend(lifecycle)

        # Inject Data Quality test cases for quarantine testing if requested
        if inject_invalid and len(all_records) > 5:
            # 1. Invalid: Missing mandatory ID
            all_records.append({
                "sr_number": None,
                "sr_type": "Pothole in Street Complaint",
                "status": "Open",
                "created_date": base_time.isoformat(),
                "last_modified_date": base_time.isoformat(),
                "street_address": "UNKNOWN"
            })
            # 2. Invalid: closed_date is earlier than created_date (Temporal Paradox)
            invalid_created = base_time + timedelta(days=5)
            invalid_closed = base_time + timedelta(days=2)
            all_records.append({
                "sr_number": "SR24-ERR-TEMPORAL-01",
                "sr_type": "Street Light 1 Out",
                "owner_department": "CDOT - Department of Transportation",
                "status": "Completed",
                "created_date": invalid_created.isoformat(),
                "closed_date": invalid_closed.isoformat(),
                "last_modified_date": invalid_created.isoformat(),
                "latitude": "41.8781",
                "longitude": "-87.6298"
            })
            # 3. Invalid: Out of Chicago bounds (e.g., coordinates in California)
            all_records.append({
                "sr_number": "SR24-ERR-BOUNDS-02",
                "sr_type": "Garbage Cart Maintenance",
                "owner_department": "Streets and Sanitation",
                "status": "Open",
                "created_date": base_time.isoformat(),
                "last_modified_date": base_time.isoformat(),
                "latitude": "34.0522",  # Los Angeles Latitude!
                "longitude": "-118.2437"
            })

        # Shuffle to simulate out-of-order / realistic ingestion streams
        random.shuffle(all_records)
        return all_records

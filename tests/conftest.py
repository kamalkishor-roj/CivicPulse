"""
Pytest Fixtures for CivicPulse Test Suite
"""

import sys
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import pytest

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.storage import LocalStorageBackend
from src.common.state_manager import StateManager
from src.transformation.duckdb_pipeline import DuckDBPipeline
from src.transformation.quality import DataQualityValidator


@pytest.fixture
def temp_dir():
    """Provides a fresh temporary directory cleaned up after test run."""
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def storage(temp_dir):
    """Provides an isolated LocalStorageBackend."""
    return LocalStorageBackend(base_dir=temp_dir)


@pytest.fixture
def state_manager(storage):
    """Provides an isolated StateManager."""
    return StateManager(storage=storage, pipeline_name="test_pipeline")


@pytest.fixture
def duckdb_pipeline(storage, temp_dir):
    """Provides an isolated DuckDBPipeline."""
    db_file = str(temp_dir / "test_civicpulse.duckdb")
    pipe = DuckDBPipeline(storage=storage, db_path=db_file)
    yield pipe
    pipe.close()


@pytest.fixture
def sample_valid_records():
    """Sample valid Chicago 311 operational service request records."""
    t0 = datetime(2024, 6, 1, 10, 0, 0)
    return [
        {
            "sr_number": "SR-TEST-101",
            "sr_type": "Pothole in Street Complaint",
            "sr_short_code": "PHF",
            "owner_department": "CDOT - Department of Transportation",
            "status": "Open",
            "created_date": t0.isoformat(),
            "last_modified_date": t0.isoformat(),
            "closed_date": None,
            "street_address": "4700 S MICHIGAN AVE",
            "zip_code": "60615",
            "ward": "4",
            "latitude": "41.8085",
            "longitude": "-87.6225",
            "duplicate": False
        },
        {
            "sr_number": "SR-TEST-102",
            "sr_type": "Garbage Cart Maintenance",
            "sr_short_code": "SRO",
            "owner_department": "Streets and Sanitation",
            "status": "In Progress",
            "created_date": (t0 - timedelta(days=2)).isoformat(),
            "last_modified_date": t0.isoformat(),
            "closed_date": None,
            "street_address": "1200 N ASHLAND AVE",
            "zip_code": "60622",
            "ward": "1",
            "latitude": "41.9038",
            "longitude": "-87.6672",
            "duplicate": False
        }
    ]

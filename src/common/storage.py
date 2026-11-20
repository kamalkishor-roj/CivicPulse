"""
Pluggable Storage Abstraction Layer for CivicPulse
Supports local filesystem staging (development/CI) and Google Cloud Storage (GCS) (cloud production).
"""

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional
from config.logging_config import logger


class StorageBackend(ABC):
    """Abstract interface for raw, bronze, silver, gold, and quarantine storage."""

    @abstractmethod
    def write_json(self, relative_path: str, data: Any) -> str:
        """Write Python data structure as JSON."""
        pass

    @abstractmethod
    def read_json(self, relative_path: str) -> Any:
        """Read JSON file into Python data structure."""
        pass

    @abstractmethod
    def write_text(self, relative_path: str, content: str) -> str:
        """Write raw text/sql file."""
        pass

    @abstractmethod
    def read_text(self, relative_path: str) -> str:
        """Read raw text file."""
        pass

    @abstractmethod
    def list_files(self, prefix: str, suffix: Optional[str] = None) -> List[str]:
        """List file paths matching prefix and optional suffix."""
        pass

    @abstractmethod
    def exists(self, relative_path: str) -> bool:
        """Check whether a path exists."""
        pass


class LocalStorageBackend(StorageBackend):
    """Local filesystem implementation of storage."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"LocalStorageBackend initialized at: {self.base_dir}")

    def _resolve(self, relative_path: str) -> Path:
        clean_rel = relative_path.lstrip("/\\")
        return self.base_dir / clean_rel

    def write_json(self, relative_path: str, data: Any) -> str:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        return str(target)

    def read_json(self, relative_path: str) -> Any:
        target = self._resolve(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {target}")
        with open(target, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_text(self, relative_path: str, content: str) -> str:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return str(target)

    def read_text(self, relative_path: str) -> str:
        target = self._resolve(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {target}")
        with open(target, "r", encoding="utf-8") as f:
            return f.read()

    def list_files(self, prefix: str, suffix: Optional[str] = None) -> List[str]:
        search_dir = self._resolve(prefix)
        if not search_dir.exists():
            return []
        results = []
        if search_dir.is_file():
            results.append(str(search_dir))
        else:
            for item in search_dir.rglob("*"):
                if item.is_file():
                    if suffix is None or item.name.endswith(suffix):
                        results.append(str(item))
        return sorted(results)

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).exists()


class GCSStorageBackend(StorageBackend):
    """Google Cloud Storage implementation of storage."""

    def __init__(self, bucket_name: str, project_id: Optional[str] = None):
        self.bucket_name = bucket_name
        self.project_id = project_id
        try:
            from google.cloud import storage
            self.client = storage.Client(project=project_id)
            self.bucket = self.client.bucket(bucket_name)
            logger.info(f"GCSStorageBackend connected to bucket: gs://{bucket_name}")
        except Exception as e:
            logger.warning(f"Could not connect to GCS bucket '{bucket_name}': {e}. Operations will fail if not using LocalStorage.")
            self.client = None
            self.bucket = None

    def write_json(self, relative_path: str, data: Any) -> str:
        if not self.bucket:
            raise RuntimeError("GCS bucket client not initialized.")
        blob_path = relative_path.lstrip("/\\").replace("\\", "/")
        blob = self.bucket.blob(blob_path)
        payload = json.dumps(data, indent=2, default=str)
        blob.upload_from_string(payload, content_type="application/json")
        return f"gs://{self.bucket_name}/{blob_path}"

    def read_json(self, relative_path: str) -> Any:
        if not self.bucket:
            raise RuntimeError("GCS bucket client not initialized.")
        blob_path = relative_path.lstrip("/\\").replace("\\", "/")
        blob = self.bucket.blob(blob_path)
        payload = blob.download_as_text()
        return json.loads(payload)

    def write_text(self, relative_path: str, content: str) -> str:
        if not self.bucket:
            raise RuntimeError("GCS bucket client not initialized.")
        blob_path = relative_path.lstrip("/\\").replace("\\", "/")
        blob = self.bucket.blob(blob_path)
        blob.upload_from_string(content, content_type="text/plain")
        return f"gs://{self.bucket_name}/{blob_path}"

    def read_text(self, relative_path: str) -> str:
        if not self.bucket:
            raise RuntimeError("GCS bucket client not initialized.")
        blob_path = relative_path.lstrip("/\\").replace("\\", "/")
        blob = self.bucket.blob(blob_path)
        return blob.download_as_text()

    def list_files(self, prefix: str, suffix: Optional[str] = None) -> List[str]:
        if not self.bucket:
            return []
        clean_prefix = prefix.lstrip("/\\").replace("\\", "/")
        blobs = self.client.list_blobs(self.bucket, prefix=clean_prefix)
        results = []
        for blob in blobs:
            if suffix is None or blob.name.endswith(suffix):
                results.append(f"gs://{self.bucket_name}/{blob.name}")
        return sorted(results)

    def exists(self, relative_path: str) -> bool:
        if not self.bucket:
            return False
        blob_path = relative_path.lstrip("/\\").replace("\\", "/")
        return self.bucket.blob(blob_path).exists()


def get_storage_backend(backend_type: str = "local", base_dir: Optional[Path] = None, bucket_name: Optional[str] = None, project_id: Optional[str] = None) -> StorageBackend:
    """Factory creating appropriate storage backend."""
    if backend_type.lower() == "gcs" and bucket_name:
        return GCSStorageBackend(bucket_name=bucket_name, project_id=project_id)
    return LocalStorageBackend(base_dir=base_dir or Path("./data"))

"""File-storage interface with local disk and S3-compatible implementations."""

from pathlib import Path
from typing import Any, Protocol

import boto3

from app.core.config import Settings, get_settings


class FileStorage(Protocol):
    """Operations shared by local and S3-compatible file stores."""

    def put(self, key: str, content: bytes) -> None:
        """Store file content under a relative key."""

    def get(self, key: str) -> bytes:
        """Read file content by key."""

    def delete(self, key: str) -> None:
        """Delete a file by key."""


class LocalFileStorage:
    """Store files beneath a configured local directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("Storage key must remain within the storage directory.")
        return path

    def put(self, key: str, content: bytes) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def get(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path_for(key).unlink()


class S3FileStorage:
    """Store files in an S3 or S3-compatible bucket."""

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, key: str, content: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=content)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


def create_file_storage(settings: Settings | None = None) -> FileStorage:
    """Select local disk or S3-compatible storage from BACKEND."""
    runtime_settings = settings or get_settings()
    if runtime_settings.backend == "local":
        return LocalFileStorage(runtime_settings.storage_path)
    runtime_settings.validate_file_storage_backend()
    client = boto3.client(
        "s3",
        endpoint_url=runtime_settings.s3_endpoint_url,
        region_name=runtime_settings.s3_region,
        aws_access_key_id=runtime_settings.s3_access_key_id,
        aws_secret_access_key=runtime_settings.s3_secret_access_key,
    )
    return S3FileStorage(client, runtime_settings.s3_bucket)

"""Private original-file storage behind a replaceable boundary."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit
from uuid import UUID


class FileStorage(Protocol):
    def put(
        self,
        *,
        user_id: str,
        attachment_id: UUID,
        name: str,
        media_type: str,
        content: bytes,
    ) -> str:
        """Store private bytes and return an internal storage URI."""

        ...

    def delete(self, storage_uri: str) -> None:
        """Delete one stored object if it exists."""

        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete every stored object owned by one user."""

        ...


def _user_namespace(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


class LocalFileStorage:
    """Private local file storage for development and deterministic tests."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        *,
        user_id: str,
        attachment_id: UUID,
        name: str,
        media_type: str,
        content: bytes,
    ) -> str:
        del media_type
        directory = self.root / _user_namespace(user_id) / str(attachment_id)
        directory.mkdir(parents=True, exist_ok=False)
        target = directory / name
        descriptor, temporary_name = tempfile.mkstemp(dir=directory, prefix=".upload-")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target.as_uri()

    def delete(self, storage_uri: str) -> None:
        parsed = urlsplit(storage_uri)
        if (
            parsed.scheme != "file"
            or parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Local attachment URI is outside the configured root.")
        target = Path(unquote(parsed.path)).resolve()
        if target == self.root or self.root not in target.parents:
            raise ValueError("Local attachment URI is outside the configured root.")
        if target.exists():
            target.unlink()
        parent = target.parent
        if parent.exists() and parent != self.root:
            parent.rmdir()

    def delete_for_user(self, user_id: str) -> None:
        directory = self.root / _user_namespace(user_id)
        if directory.exists() and directory.parent == self.root:
            shutil.rmtree(directory)


class GCSFileStorage:
    """Google Cloud Storage implementation with no public URL generation."""

    def __init__(
        self,
        *,
        bucket_name: str,
        client: Any | None = None,
    ) -> None:
        if client is None:
            try:
                from google.cloud import storage  # pyright: ignore[reportMissingTypeStubs]
            except ImportError as error:  # pragma: no cover - packaging guard
                raise RuntimeError(
                    "google-cloud-storage is required with GCS file storage."
                ) from error
            client = storage.Client()
        self.client = client
        self.bucket_name = bucket_name
        self.bucket = client.bucket(bucket_name)

    @staticmethod
    def _object_name(user_id: str, attachment_id: UUID, name: str) -> str:
        return f"users/{_user_namespace(user_id)}/{attachment_id}/{name}"

    def put(
        self,
        *,
        user_id: str,
        attachment_id: UUID,
        name: str,
        media_type: str,
        content: bytes,
    ) -> str:
        object_name = self._object_name(user_id, attachment_id, name)
        blob = self.bucket.blob(object_name)
        blob.upload_from_string(content, content_type=media_type, if_generation_match=0)
        return f"gs://{self.bucket_name}/{object_name}"

    def delete(self, storage_uri: str) -> None:
        prefix = f"gs://{self.bucket_name}/"
        if not storage_uri.startswith(prefix):
            raise ValueError("Attachment URI is outside the configured bucket.")
        try:
            self.bucket.blob(storage_uri.removeprefix(prefix)).delete()
        except Exception as error:
            # Deletion is intentionally idempotent for account-removal retries.
            if getattr(error, "code", None) != 404:
                raise

    def delete_for_user(self, user_id: str) -> None:
        prefix = f"users/{_user_namespace(user_id)}/"
        for blob in self.client.list_blobs(self.bucket_name, prefix=prefix):
            blob.delete()

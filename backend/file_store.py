"""Tenant-scoped attachment metadata persistence."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from .models import Attachment


class AttachmentNotFoundError(LookupError):
    """Raised when an attachment is absent or belongs to another user."""


class JsonAttachmentRepository:
    """Persist local attachment metadata with atomic file replacement."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"attachments": []}
        try:
            raw: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise RuntimeError("Local attachment metadata could not be read.") from error
        if not isinstance(raw, dict):
            raise RuntimeError("Local attachment metadata has an invalid shape.")
        values = cast(dict[str, object], raw).get("attachments", [])
        if not isinstance(values, list):
            raise RuntimeError("Local attachment metadata has an invalid shape.")
        return {
            "attachments": [
                cast(dict[str, Any], value)
                for value in cast(list[object], values)
                if isinstance(value, dict)
            ]
        }

    def _write(self, payload: dict[str, list[dict[str, Any]]]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def list_attachments(self, user_id: str) -> list[Attachment]:
        with self._lock:
            attachments = [
                Attachment.model_validate(value)
                for value in self._read()["attachments"]
                if value.get("user_id") == user_id
            ]
        return sorted(attachments, key=lambda item: item.updated_at, reverse=True)

    def get_attachment(
        self,
        attachment_id: UUID | str,
        user_id: str,
    ) -> Attachment:
        requested_id = str(attachment_id)
        for attachment in self.list_attachments(user_id):
            if str(attachment.id) == requested_id:
                return attachment
        raise AttachmentNotFoundError("Attachment does not exist for this user.")

    def create_attachment(self, attachment: Attachment) -> Attachment:
        with self._lock:
            payload = self._read()
            if any(
                str(value.get("id")) == str(attachment.id)
                for value in payload["attachments"]
            ):
                raise ValueError("Attachment already exists.")
            payload["attachments"].append(attachment.model_dump(mode="json"))
            self._write(payload)
        return attachment

    def save_attachment(self, attachment: Attachment, user_id: str) -> Attachment:
        if attachment.user_id != user_id:
            raise AttachmentNotFoundError(
                "Attachment does not exist for this user."
            )
        with self._lock:
            payload = self._read()
            for index, value in enumerate(payload["attachments"]):
                if str(value.get("id")) != str(attachment.id):
                    continue
                if value.get("user_id") != user_id:
                    break
                payload["attachments"][index] = attachment.model_dump(mode="json")
                self._write(payload)
                return attachment
        raise AttachmentNotFoundError("Attachment does not exist for this user.")

    def delete_attachment(self, attachment_id: UUID | str, user_id: str) -> None:
        requested_id = str(attachment_id)
        with self._lock:
            payload = self._read()
            retained = [
                value
                for value in payload["attachments"]
                if not (
                    str(value.get("id")) == requested_id
                    and value.get("user_id") == user_id
                )
            ]
            if len(retained) == len(payload["attachments"]):
                raise AttachmentNotFoundError(
                    "Attachment does not exist for this user."
                )
            payload["attachments"] = retained
            self._write(payload)

    def delete_for_user(self, user_id: str) -> None:
        with self._lock:
            payload = self._read()
            payload["attachments"] = [
                value
                for value in payload["attachments"]
                if value.get("user_id") != user_id
            ]
            self._write(payload)

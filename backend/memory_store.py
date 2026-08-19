"""Local JSON persistence for the user-controlled Memory Ledger."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from .memory_embedding import coerce_float_list, cosine_similarity
from .models import Memory


class MemoryNotFoundError(LookupError):
    """Raised when a memory is absent or belongs to another user."""


class JsonMemoryRepository:
    """Persist memories in one ignored local file with atomic replacement."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"memories": []}
        try:
            raw_payload: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise RuntimeError("The local Memory Ledger could not be read.") from error
        if not isinstance(raw_payload, dict):
            raise RuntimeError("The local Memory Ledger has an invalid shape.")
        payload = cast(dict[str, object], raw_payload)
        raw_memories = payload.get("memories", [])
        if not isinstance(raw_memories, list):
            raise RuntimeError("The local Memory Ledger has an invalid shape.")
        memories = [
            cast(dict[str, Any], item)
            for item in cast(list[object], raw_memories)
            if isinstance(item, dict)
        ]
        return {"memories": memories}

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

    def list_memories(self, user_id: str) -> list[Memory]:
        with self._lock:
            memories = [
                Memory.model_validate(_public_memory_payload(item))
                for item in self._read()["memories"]
                if item.get("user_id") == user_id
            ]
        return sorted(memories, key=lambda item: item.updated_at, reverse=True)

    def get_memory(self, memory_id: UUID | str, user_id: str) -> Memory:
        requested_id = str(memory_id)
        for memory in self.list_memories(user_id):
            if str(memory.id) == requested_id:
                return memory
        raise MemoryNotFoundError("Memory does not exist for this user.")

    def create_memory(self, memory: Memory) -> Memory:
        with self._lock:
            payload = self._read()
            if any(
                str(item.get("id")) == str(memory.id)
                for item in payload["memories"]
            ):
                raise ValueError("Memory already exists.")
            payload["memories"].append(memory.model_dump(mode="json"))
            self._write(payload)
        return memory

    def upsert_memory(self, memory: Memory) -> Memory:
        with self._lock:
            payload = self._read()
            for item in payload["memories"]:
                if str(item.get("id")) != str(memory.id):
                    continue
                if item.get("user_id") != memory.user_id:
                    raise MemoryNotFoundError("Memory does not exist for this user.")
                return Memory.model_validate(_public_memory_payload(item))
            payload["memories"].append(memory.model_dump(mode="json"))
            self._write(payload)
        return memory

    def save_memory(self, memory: Memory, user_id: str) -> Memory:
        if memory.user_id != user_id:
            raise MemoryNotFoundError("Memory does not exist for this user.")
        with self._lock:
            payload = self._read()
            for index, item in enumerate(payload["memories"]):
                if str(item.get("id")) != str(memory.id):
                    continue
                if item.get("user_id") != user_id:
                    break
                private_fields = {
                    key: value
                    for key, value in item.items()
                    if key.startswith("_embedding")
                }
                payload["memories"][index] = {
                    **memory.model_dump(mode="json"),
                    **private_fields,
                }
                self._write(payload)
                return memory
        raise MemoryNotFoundError("Memory does not exist for this user.")

    def memory_embedding(
        self,
        memory_id: UUID | str,
        user_id: str,
    ) -> tuple[str, list[float]] | None:
        requested_id = str(memory_id)
        with self._lock:
            for item in self._read()["memories"]:
                if str(item.get("id")) != requested_id:
                    continue
                if item.get("user_id") != user_id:
                    break
                model = item.get("_embedding_model")
                vector = item.get("_embedding")
                if not isinstance(model, str) or not isinstance(vector, list):
                    return None
                converted = coerce_float_list(cast(list[object], vector))
                return (model, converted) if converted is not None else None
        raise MemoryNotFoundError("Memory does not exist for this user.")

    def save_memory_embedding(
        self,
        memory_id: UUID | str,
        user_id: str,
        *,
        model: str,
        vector: list[float],
    ) -> None:
        requested_id = str(memory_id)
        with self._lock:
            payload = self._read()
            for item in payload["memories"]:
                if str(item.get("id")) != requested_id:
                    continue
                if item.get("user_id") != user_id:
                    break
                item["_embedding_model"] = model
                item["_embedding"] = [float(value) for value in vector]
                self._write(payload)
                return
        raise MemoryNotFoundError("Memory does not exist for this user.")

    def find_similar_memories(
        self,
        user_id: str,
        vector: list[float],
        *,
        limit: int,
    ) -> list[tuple[Memory, float]]:
        matches: list[tuple[Memory, float]] = []
        with self._lock:
            for item in self._read()["memories"]:
                if item.get("user_id") != user_id:
                    continue
                raw_vector = item.get("_embedding")
                if not isinstance(raw_vector, list):
                    continue
                embedding = coerce_float_list(cast(list[object], raw_vector))
                if embedding is None:
                    continue
                score = cosine_similarity(vector, embedding)
                matches.append(
                    (Memory.model_validate(_public_memory_payload(item)), score)
                )
        matches.sort(key=lambda item: item[1], reverse=True)
        return matches[:limit]

    def delete_memory(self, memory_id: UUID | str, user_id: str) -> None:
        requested_id = str(memory_id)
        with self._lock:
            payload = self._read()
            for index, item in enumerate(payload["memories"]):
                if str(item.get("id")) != requested_id:
                    continue
                if item.get("user_id") != user_id:
                    break
                payload["memories"].pop(index)
                self._write(payload)
                return
        raise MemoryNotFoundError("Memory does not exist for this user.")

    def delete_for_user(self, user_id: str) -> None:
        with self._lock:
            payload = self._read()
            retained = [
                item
                for item in payload["memories"]
                if item.get("user_id") != user_id
            ]
            if len(retained) == len(payload["memories"]):
                return
            payload["memories"] = retained
            self._write(payload)


def _public_memory_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}

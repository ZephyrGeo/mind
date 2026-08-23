"""Persistent, tenant-scoped usage limits for reviewer-facing deployments."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast


class _UsagePayload(TypedDict):
    daily_usage: dict[str, dict[str, dict[str, int]]]
    active_research: dict[str, list[str]]


class DailyUsageLimitExceeded(RuntimeError):
    """Raised before a provider call would exceed a user's daily allowance."""

    def __init__(self, *, resource: str, limit: int) -> None:
        self.resource = resource
        self.limit = limit
        super().__init__(f"Daily {resource} limit reached ({limit}).")


class ActiveResearchLimitExceeded(RuntimeError):
    """Raised when a user already owns the maximum active Research jobs."""

    def __init__(self, *, limit: int) -> None:
        self.limit = limit
        super().__init__(
            "Finish or stop the current Research task before starting another."
        )


class UsageLimitRepository(Protocol):
    def consume_chat(self, user_id: str, *, day: str, limit: int) -> int:
        """Atomically consume one Chat request and return the new daily count."""

        ...

    def rollback_chat(self, user_id: str, *, day: str) -> None:
        """Refund a Chat reservation rejected before provider work."""

        ...

    def reserve_research(
        self,
        user_id: str,
        job_id: str,
        *,
        day: str,
        daily_limit: int,
        active_limit: int,
        count_daily: bool,
    ) -> int:
        """Atomically claim an active slot and optionally consume daily usage."""

        ...

    def release_research(self, user_id: str, job_id: str) -> None:
        """Release one active Research slot without refunding daily usage."""

        ...

    def rollback_research(
        self,
        user_id: str,
        job_id: str,
        *,
        day: str,
        refund_daily: bool,
    ) -> None:
        """Undo a reservation when Research failed before any provider work."""

        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete usage state owned by exactly one user."""

        ...


def utc_usage_day(now: datetime | None = None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).date().isoformat()


class JsonUsageLimitRepository:
    """Atomic local JSON usage ledger used by development and tests."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self) -> _UsagePayload:
        if not self.file_path.exists():
            return {"daily_usage": {}, "active_research": {}}
        with self.file_path.open("r", encoding="utf-8") as handle:
            raw_payload: object = json.load(handle)
        if not isinstance(raw_payload, dict):
            raise ValueError("Usage data file has an invalid shape.")
        payload = cast(dict[str, object], raw_payload)
        daily_usage = payload.get("daily_usage", {})
        active_research = payload.get("active_research", {})
        if not isinstance(daily_usage, dict) or not isinstance(
            active_research, dict
        ):
            raise ValueError("Usage data file has an invalid shape.")
        return {
            "daily_usage": cast(
                dict[str, dict[str, dict[str, int]]],
                daily_usage,
            ),
            "active_research": cast(dict[str, list[str]], active_research),
        }

    def _write(self, payload: _UsagePayload) -> None:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.file_path.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, self.file_path)

    @staticmethod
    def _daily_record(
        payload: _UsagePayload,
        user_id: str,
        day: str,
    ) -> dict[str, int]:
        users = payload["daily_usage"]
        user_days = users.setdefault(user_id, {})
        record = user_days.setdefault(day, {"chat": 0, "research": 0})
        return record

    def consume_chat(self, user_id: str, *, day: str, limit: int) -> int:
        with self._lock:
            payload = self._read()
            record = self._daily_record(payload, user_id, day)
            count = int(record.get("chat", 0))
            if count >= limit:
                raise DailyUsageLimitExceeded(resource="Chat", limit=limit)
            count += 1
            record["chat"] = count
            self._write(payload)
            return count

    def reserve_research(
        self,
        user_id: str,
        job_id: str,
        *,
        day: str,
        daily_limit: int,
        active_limit: int,
        count_daily: bool,
    ) -> int:
        with self._lock:
            payload = self._read()
            active_ids = list(
                payload["active_research"].setdefault(user_id, [])
            )
            record = self._daily_record(payload, user_id, day)
            count = int(record.get("research", 0))
            if job_id in active_ids:
                return count
            if len(active_ids) >= active_limit:
                raise ActiveResearchLimitExceeded(limit=active_limit)
            if count_daily and count >= daily_limit:
                raise DailyUsageLimitExceeded(
                    resource="Research",
                    limit=daily_limit,
                )
            if count_daily:
                count += 1
                record["research"] = count
            active_ids.append(job_id)
            payload["active_research"][user_id] = active_ids
            self._write(payload)
            return count

    def rollback_chat(self, user_id: str, *, day: str) -> None:
        with self._lock:
            payload = self._read()
            record = self._daily_record(payload, user_id, day)
            count = int(record.get("chat", 0))
            if count <= 0:
                return
            record["chat"] = count - 1
            self._write(payload)

    def release_research(self, user_id: str, job_id: str) -> None:
        with self._lock:
            payload = self._read()
            active = payload["active_research"].get(user_id, [])
            if job_id not in active:
                return
            remaining = [value for value in active if value != job_id]
            if remaining:
                payload["active_research"][user_id] = remaining
            else:
                payload["active_research"].pop(user_id, None)
            self._write(payload)

    def rollback_research(
        self,
        user_id: str,
        job_id: str,
        *,
        day: str,
        refund_daily: bool,
    ) -> None:
        with self._lock:
            payload = self._read()
            active = payload["active_research"].get(user_id, [])
            if job_id not in active:
                return
            remaining = [value for value in active if value != job_id]
            if remaining:
                payload["active_research"][user_id] = remaining
            else:
                payload["active_research"].pop(user_id, None)
            if refund_daily:
                record = self._daily_record(payload, user_id, day)
                record["research"] = max(
                    0,
                    int(record.get("research", 0)) - 1,
                )
            self._write(payload)

    def delete_for_user(self, user_id: str) -> None:
        with self._lock:
            payload = self._read()
            changed = False
            if payload["daily_usage"].pop(user_id, None) is not None:
                changed = True
            if payload["active_research"].pop(user_id, None) is not None:
                changed = True
            if changed:
                self._write(payload)


TransactionFactory = Callable[[Callable[[Any], Any]], Callable[[Any], Any]]


class FirestoreUsageLimitRepository:
    """Server-only Firestore counters with transaction-safe reservations."""

    def __init__(
        self,
        *,
        project_id: str,
        database_id: str = "(default)",
        client: Any | None = None,
        transactional: TransactionFactory | None = None,
    ) -> None:
        resolved_client: Any = client
        resolved_transactional = transactional
        if resolved_client is None:
            try:
                from google.cloud import firestore  # pyright: ignore[reportMissingTypeStubs]
            except ImportError as error:  # pragma: no cover - packaging guard
                raise RuntimeError(
                    "google-cloud-firestore is required when "
                    "MIND_PERSISTENCE_PROVIDER=firestore."
                ) from error
            resolved_client = firestore.Client(
                project=project_id,
                database=database_id,
            )
            resolved_transactional = cast(
                TransactionFactory,
                firestore.transactional,  # pyright: ignore[reportUnknownMemberType]
            )
        if resolved_transactional is None:
            raise ValueError("A transactional adapter is required with a custom client.")
        self.client: Any = resolved_client
        self._transactional: TransactionFactory = resolved_transactional

    def _root(self, user_id: str) -> Any:
        return self.client.collection("usage_limits").document(user_id)

    def _day(self, user_id: str, day: str) -> Any:
        return self._root(user_id).collection("days").document(day)

    def _research_state(self, user_id: str) -> Any:
        return self._root(user_id).collection("state").document("research")

    def _run_transaction(self, operation: Callable[[Any], Any]) -> Any:
        return self._transactional(operation)(self.client.transaction())

    @staticmethod
    def _payload(snapshot: Any) -> dict[str, Any]:
        payload: object = snapshot.to_dict() if snapshot.exists else {}
        if not isinstance(payload, dict):
            return {}
        return cast(dict[str, Any], payload)

    def consume_chat(self, user_id: str, *, day: str, limit: int) -> int:
        reference = self._day(user_id, day)

        def operation(transaction: Any) -> int:
            payload = self._payload(reference.get(transaction=transaction))
            count = int(payload.get("chat", 0))
            if count >= limit:
                raise DailyUsageLimitExceeded(resource="Chat", limit=limit)
            count += 1
            transaction.set(
                reference,
                {
                    **payload,
                    "user_id": user_id,
                    "day": day,
                    "chat": count,
                    "research": int(payload.get("research", 0)),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            return count

        return self._run_transaction(operation)

    def reserve_research(
        self,
        user_id: str,
        job_id: str,
        *,
        day: str,
        daily_limit: int,
        active_limit: int,
        count_daily: bool,
    ) -> int:
        day_reference = self._day(user_id, day)
        state_reference = self._research_state(user_id)

        def operation(transaction: Any) -> int:
            day_payload = self._payload(
                day_reference.get(transaction=transaction)
            )
            state_payload = self._payload(
                state_reference.get(transaction=transaction)
            )
            active_ids = [
                str(value)
                for value in state_payload.get("active_job_ids", [])
            ]
            count = int(day_payload.get("research", 0))
            if job_id in active_ids:
                return count
            if len(active_ids) >= active_limit:
                raise ActiveResearchLimitExceeded(limit=active_limit)
            if count_daily and count >= daily_limit:
                raise DailyUsageLimitExceeded(
                    resource="Research",
                    limit=daily_limit,
                )
            if count_daily:
                count += 1
            active_ids.append(job_id)
            now = datetime.now(timezone.utc).isoformat()
            transaction.set(
                day_reference,
                {
                    **day_payload,
                    "user_id": user_id,
                    "day": day,
                    "chat": int(day_payload.get("chat", 0)),
                    "research": count,
                    "updated_at": now,
                },
            )
            transaction.set(
                state_reference,
                {
                    "user_id": user_id,
                    "active_job_ids": active_ids,
                    "updated_at": now,
                },
            )
            return count

        return self._run_transaction(operation)

    def rollback_chat(self, user_id: str, *, day: str) -> None:
        reference = self._day(user_id, day)

        def operation(transaction: Any) -> None:
            payload = self._payload(reference.get(transaction=transaction))
            count = int(payload.get("chat", 0))
            if count <= 0:
                return
            transaction.set(
                reference,
                {
                    **payload,
                    "user_id": user_id,
                    "day": day,
                    "chat": count - 1,
                    "research": int(payload.get("research", 0)),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        self._run_transaction(operation)

    def release_research(self, user_id: str, job_id: str) -> None:
        reference = self._research_state(user_id)

        def operation(transaction: Any) -> None:
            payload = self._payload(reference.get(transaction=transaction))
            active_ids = [
                str(value)
                for value in payload.get("active_job_ids", [])
                if str(value) != job_id
            ]
            if len(active_ids) == len(payload.get("active_job_ids", [])):
                return
            transaction.set(
                reference,
                {
                    "user_id": user_id,
                    "active_job_ids": active_ids,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        self._run_transaction(operation)

    def rollback_research(
        self,
        user_id: str,
        job_id: str,
        *,
        day: str,
        refund_daily: bool,
    ) -> None:
        day_reference = self._day(user_id, day)
        state_reference = self._research_state(user_id)

        def operation(transaction: Any) -> None:
            state_payload = self._payload(
                state_reference.get(transaction=transaction)
            )
            day_payload = (
                self._payload(day_reference.get(transaction=transaction))
                if refund_daily
                else {}
            )
            original_ids = [
                str(value)
                for value in state_payload.get("active_job_ids", [])
            ]
            if job_id not in original_ids:
                return
            now = datetime.now(timezone.utc).isoformat()
            transaction.set(
                state_reference,
                {
                    "user_id": user_id,
                    "active_job_ids": [
                        value for value in original_ids if value != job_id
                    ],
                    "updated_at": now,
                },
            )
            if refund_daily:
                transaction.set(
                    day_reference,
                    {
                        **day_payload,
                        "user_id": user_id,
                        "day": day,
                        "chat": int(day_payload.get("chat", 0)),
                        "research": max(
                            0,
                            int(day_payload.get("research", 0)) - 1,
                        ),
                        "updated_at": now,
                    },
                )

        self._run_transaction(operation)

    def delete_for_user(self, user_id: str) -> None:
        root = self._root(user_id)
        for collection_name in ("days", "state"):
            collection = root.collection(collection_name)
            for snapshot in list(collection.stream()):
                snapshot.reference.delete()
        root.delete()

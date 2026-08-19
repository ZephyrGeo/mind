"""Hybrid semantic retrieval for relevant, user-approved memories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Sequence
from typing import Protocol

from .memory_embedding import EmbeddingProvider, HashEmbeddingProvider
from .models import Memory, MemoryStatus
from .repositories import MemoryRepository


@dataclass(frozen=True, slots=True)
class MemoryMatch:
    memory: Memory
    score: float


class MemoryRetriever(Protocol):
    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        limit: int,
    ) -> list[MemoryMatch]:
        """Return only relevant, active, enabled, unexpired memories."""

        ...

    def related(
        self,
        user_id: str,
        text: str,
        *,
        limit: int,
        memories: Sequence[Memory] | None = None,
    ) -> list[MemoryMatch]:
        """Return semantically related entries for reconciliation."""

        ...

    def embed_memory(self, memory: Memory) -> None:
        """Persist or refresh the semantic vector for one memory."""

        ...


class LocalMemoryRetriever:
    """Hybrid vector and lexical retrieval over the configured repository."""

    def __init__(
        self,
        repository: MemoryRepository,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        semantic_threshold: float = 0.68,
    ) -> None:
        if not 0 <= semantic_threshold <= 1:
            raise ValueError("Memory semantic threshold must be between 0 and 1.")
        self.repository = repository
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()
        self.semantic_threshold = semantic_threshold

    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        limit: int,
    ) -> list[MemoryMatch]:
        memories = [
            memory
            for memory in self.repository.list_memories(user_id)
            if _is_retrievable(memory)
        ]
        return self._rank(
            user_id,
            query,
            memories,
            limit=limit,
            threshold=self.semantic_threshold,
        )

    def related(
        self,
        user_id: str,
        text: str,
        *,
        limit: int,
        memories: Sequence[Memory] | None = None,
    ) -> list[MemoryMatch]:
        candidates = [
            memory
            for memory in (
                memories
                if memories is not None
                else self.repository.list_memories(user_id)
            )
            if memory.status != MemoryStatus.SUPERSEDED
        ]
        return self._rank(
            user_id,
            text,
            candidates,
            limit=limit,
            threshold=max(0.55, self.semantic_threshold - 0.08),
        )

    def embed_memory(self, memory: Memory) -> None:
        vectors = self.embedding_provider.embed([_embedding_text(memory)])
        if not vectors:
            return
        self.repository.save_memory_embedding(
            memory.id,
            memory.user_id,
            model=self.embedding_provider.model,
            vector=vectors[0],
        )

    def _rank(
        self,
        user_id: str,
        query: str,
        memories: list[Memory],
        *,
        limit: int,
        threshold: float,
    ) -> list[MemoryMatch]:
        if not query.strip() or not memories or limit < 1:
            return []
        candidates = memories[:200]
        semantic_scores: dict[str, float] = {}
        try:
            self._ensure_embeddings(candidates)
            query_vectors = self.embedding_provider.embed([query])
            if query_vectors:
                semantic_scores = {
                    str(memory.id): score
                    for memory, score in self.repository.find_similar_memories(
                        user_id,
                        query_vectors[0],
                        limit=min(200, max(limit * 6, 24)),
                    )
                }
        except Exception:
            # Context retrieval remains available during an embedding outage.
            semantic_scores = {}

        query_terms = _terms(query)
        normalized_query = " ".join(query.casefold().split())
        matches: list[MemoryMatch] = []
        for memory in candidates:
            content = _embedding_text(memory).casefold()
            overlap = len(query_terms & _terms(content))
            semantic = semantic_scores.get(str(memory.id), 0.0)
            exact_bonus = (
                2.0
                if normalized_query
                and (normalized_query in content or content in normalized_query)
                else 0.0
            )
            if semantic < threshold and overlap == 0 and exact_bonus == 0:
                continue
            score = semantic * 5.0 + min(overlap, 5) + exact_bonus
            if memory.pinned:
                score += 1.5
            matches.append(MemoryMatch(memory=memory, score=score))
        matches.sort(
            key=lambda item: (
                item.score,
                item.memory.pinned,
                item.memory.updated_at,
            ),
            reverse=True,
        )
        return matches[:limit]

    def _ensure_embeddings(self, memories: list[Memory]) -> None:
        missing: list[Memory] = []
        for memory in memories:
            stored = self.repository.memory_embedding(memory.id, memory.user_id)
            if (
                stored is None
                or stored[0] != self.embedding_provider.model
                or len(stored[1]) != self.embedding_provider.dimensions
            ):
                missing.append(memory)
        for offset in range(0, len(missing), 64):
            batch = missing[offset : offset + 64]
            vectors = self.embedding_provider.embed(
                [_embedding_text(memory) for memory in batch]
            )
            if len(vectors) != len(batch):
                continue
            for memory, vector in zip(batch, vectors, strict=True):
                self.repository.save_memory_embedding(
                    memory.id,
                    memory.user_id,
                    model=self.embedding_provider.model,
                    vector=vector,
                )
def _embedding_text(memory: Memory) -> str:
    if not memory.facets:
        return memory.content
    return "\n".join((memory.content, *(f"- {facet}" for facet in memory.facets)))


def _is_retrievable(memory: Memory, *, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(timezone.utc)
    return (
        memory.status == MemoryStatus.ACTIVE
        and memory.enabled
        and (memory.expires_at is None or memory.expires_at > current_time)
        and (memory.stale_after is None or memory.stale_after > current_time)
    )


def _terms(value: str) -> set[str]:
    normalized = value.casefold()
    words = set(re.findall(r"[a-z0-9][a-z0-9_-]{1,}|[\u3400-\u9fff]", normalized))
    chinese = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    words.update(
        chinese[index : index + 2]
        for index in range(max(0, len(chinese) - 1))
    )
    return words

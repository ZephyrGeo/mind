"""Embedding provider boundary for semantic Memory retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider cannot produce a valid vector."""


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int
    billable_calls: bool

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one normalized vector for every input text in order."""

        ...


class HashEmbeddingProvider:
    """Deterministic local/test fallback with no network calls or cloud cost."""

    name = "local_hash"
    billable_calls = False

    def __init__(self, *, dimensions: int = 256) -> None:
        if not 32 <= dimensions <= 2_048:
            raise ValueError("Embedding dimensions must be between 32 and 2048.")
        self.dimensions = dimensions
        self.model = f"mind-hash-embedding-{dimensions}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        terms = _terms(text)
        if not terms:
            return vector
        for term in terms:
            digest = hashlib.sha256(term.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        return _normalize(vector)


class OpenAIEmbeddingProvider:
    """Create multilingual embeddings through the OpenAI Embeddings API."""

    name = "openai"
    billable_calls = True

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "text-embedding-3-small",
        dimensions: int = 256,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 8_000_000,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OpenAI base URL must be a safe HTTPS origin.")
        if not model or any(character.isspace() for character in model):
            raise ValueError("Embedding model must be a non-empty model ID.")
        if not 32 <= dimensions <= 2_048:
            raise ValueError("Embedding dimensions must be between 32 and 2048.")
        if timeout_seconds <= 0 or max_response_bytes < 1:
            raise ValueError("Embedding provider limits must be positive.")
        self._api_key = (api_key or "").strip()
        self.configured = bool(self._api_key)
        self.model = model
        self.dimensions = dimensions
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._opener = opener

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.configured:
            raise EmbeddingProviderError("OpenAI Embeddings is not configured.")
        bounded = [" ".join(text.split())[:8_000] for text in texts]
        body = {
            "model": self.model,
            "input": bounded,
            "dimensions": self.dimensions,
            "encoding_format": "float",
        }
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        request = Request(
            f"{self.base_url}/embeddings",
            data=encoded,
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "mind-personal-agent/0.7",
            },
        )
        try:
            response = self._opener(request, timeout=self.timeout_seconds)
            with response:
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as error:
            raise EmbeddingProviderError(
                f"OpenAI Embeddings failed with HTTP {error.code}."
            ) from None
        except (TimeoutError, URLError, OSError) as error:
            raise EmbeddingProviderError(
                "OpenAI Embeddings is temporarily unavailable."
            ) from error
        if len(raw) > self.max_response_bytes:
            raise EmbeddingProviderError("OpenAI Embeddings response was too large.")
        try:
            payload: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EmbeddingProviderError(
                "OpenAI returned invalid Embeddings JSON."
            ) from error
        if not isinstance(payload, Mapping):
            raise EmbeddingProviderError("OpenAI returned invalid Embeddings data.")
        payload_map = cast(Mapping[str, object], payload)
        raw_data = payload_map.get("data")
        if not isinstance(raw_data, list):
            raise EmbeddingProviderError("OpenAI returned invalid Embeddings data.")
        indexed: dict[int, list[float]] = {}
        for raw_item in cast(list[object], raw_data):
            if not isinstance(raw_item, Mapping):
                continue
            item = cast(Mapping[str, object], raw_item)
            raw_index = item.get("index")
            raw_vector = item.get("embedding")
            if not isinstance(raw_index, int) or not isinstance(raw_vector, list):
                continue
            vector = coerce_float_list(cast(list[object], raw_vector))
            if vector is None:
                continue
            if len(vector) == self.dimensions:
                indexed[raw_index] = _normalize(vector)
        if sorted(indexed) != list(range(len(bounded))):
            raise EmbeddingProviderError("OpenAI returned incomplete Embeddings data.")
        return [indexed[index] for index in range(len(bounded))]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [float(value / norm) for value in vector] if norm else [0.0] * len(vector)


def coerce_float_list(values: Sequence[object]) -> list[float] | None:
    """Convert a provider or persistence vector to Python floats."""

    converted: list[float] = []
    for value in values:
        if not isinstance(value, (int, float, str)):
            return None
        try:
            converted.append(float(value))
        except ValueError:
            return None
    return converted


def _terms(value: str) -> set[str]:
    normalized = value.casefold()
    words = set(re.findall(r"[a-z0-9][a-z0-9_-]{1,}", normalized))
    chinese = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    words.update(chinese[index : index + 2] for index in range(len(chinese) - 1))
    return words

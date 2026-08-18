"""Stable URL identity for Research sources and citations."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


_TRACKING_QUERY_KEYS = frozenset(
    {
        "adobe_mc",
        "adobe_mc_ref",
        "dclid",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "msclkid",
    }
)
_OPENAI_DOC_HOSTS = frozenset(
    {
        "developers.openai.com",
        "platform.openai.com",
    }
)
_OPENAI_PRESENTATION_QUERY_KEYS = frozenset({"api-mode", "lang"})


def canonical_source_url(value: str) -> str:
    """Return a safe, displayable identity URL with tracking noise removed."""

    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""

    host = _canonical_host(parsed.hostname)
    if not host:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    path = _clean_path(parsed.path or "/", host)
    host, path = _canonical_openai_doc_location(host, path)
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and not default_port:
        netloc = f"{netloc}:{port}"
    query_items: list[tuple[str, str]] = []
    for key, query_value in parse_qsl(
        parsed.query,
        keep_blank_values=True,
    ):
        normalized_key = key.casefold()
        if _is_tracking_key(normalized_key):
            continue
        if (
            host in _OPENAI_DOC_HOSTS
            and normalized_key in _OPENAI_PRESENTATION_QUERY_KEYS
        ):
            continue
        query_items.append((key, query_value))
    query_items.sort(key=lambda item: (item[0].casefold(), item[1]))

    return urlunsplit(
        (
            scheme,
            netloc,
            path.rstrip("/") or "/",
            urlencode(query_items, doseq=True),
            "",
        )
    )


def _canonical_host(hostname: str) -> str:
    host = hostname.casefold().rstrip(".")
    if ":" in host:
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def _clean_path(path: str, host: str) -> str:
    if host not in _OPENAI_DOC_HOSTS:
        return path
    encoded_query = re.search(r"%3f", path, flags=re.IGNORECASE)
    if encoded_query is None:
        return path
    suffix = unquote(path[encoded_query.end() :])
    first_key = suffix.split("=", 1)[0].casefold()
    if _is_tracking_key(first_key):
        return path[: encoded_query.start()]
    return path


def _canonical_openai_doc_location(host: str, path: str) -> tuple[str, str]:
    """Unify legacy OpenAI guide URLs with their current canonical host."""

    legacy_prefix = "/docs/guides/"
    if host == "platform.openai.com" and path.startswith(legacy_prefix):
        return (
            "developers.openai.com",
            f"/api/docs/guides/{path.removeprefix(legacy_prefix)}",
        )
    return host, path


def _is_tracking_key(key: str) -> bool:
    return key.startswith("utm_") or key in _TRACKING_QUERY_KEYS

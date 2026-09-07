"""Hosted CourtListener citation lookup. Do not invent case law."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import ApiError

BASE = "https://www.courtlistener.com/api/rest/v4"
CACHE_TTL_S = 24 * 60 * 60
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _headers() -> dict[str, str]:
    token = get_settings().courtlistener_api_token.strip()
    if not token:
        raise ApiError(
            503,
            "Citation lookup is temporarily unavailable.",
            "citation_lookup_unavailable",
        )
    return {"Authorization": f"Token {token}"}


def cache_get(citation: str) -> list[dict[str, Any]] | None:
    hit = _CACHE.get(citation)
    if not hit:
        return None
    expires, payload = hit
    if time.time() > expires:
        _CACHE.pop(citation, None)
        return None
    return payload


def cache_set(citation: str, payload: list[dict[str, Any]]) -> None:
    _CACHE[citation] = (time.time() + CACHE_TTL_S, payload)


def clear_cache() -> None:
    _CACHE.clear()


async def lookup_citation(citation: str, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    cached = cache_get(citation)
    if cached is not None:
        return cached
    url = f"{BASE}/search/"
    params = {"type": "o", "q": f'"{citation}"'}
    own = client is None
    http = client or httpx.AsyncClient(timeout=20.0)
    try:
        res = await http.get(url, params=params, headers=_headers())
    except httpx.HTTPError:
        raise ApiError(502, "Citation lookup is temporarily unavailable.", "citation_lookup_unavailable")
    finally:
        if own:
            await http.aclose()

    if res.status_code == 429:
        raise ApiError(429, "Too many citation lookups right now. Please wait a moment.", "rate_limited")
    if res.status_code in (401, 403):
        raise ApiError(502, "Citation lookup is temporarily unavailable.", "citation_lookup_unavailable")
    if res.status_code >= 400:
        raise ApiError(502, "Citation lookup is temporarily unavailable.", "citation_lookup_unavailable")

    data = res.json() if res.content else {}
    results = data.get("results") if isinstance(data, dict) else None
    first = results[0] if isinstance(results, list) and results else None
    count = data.get("count") if isinstance(data, dict) else 0
    if count and isinstance(first, dict):
        payload = [
            {
                "citation": citation,
                "status": 200,
                "clusters": [
                    {
                        "id": first.get("cluster_id"),
                        "case_name": first.get("caseName"),
                        "court": first.get("court"),
                        "date_filed": first.get("dateFiled"),
                        "absolute_url": first.get("absolute_url"),
                    }
                ],
            }
        ]
    else:
        payload = [{"citation": citation, "status": 404, "clusters": []}]
    cache_set(citation, payload)
    return payload

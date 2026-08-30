"""OpenAI-compatible JSON and token-stream client."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import ApiError

# Injected by tests. When set, complete_json / stream_tokens use it instead of the network.
_json_override: Any | None = None
_stream_override: Any | None = None


def set_llm_overrides(*, complete_json: Any | None = None, stream_tokens: Any | None = None) -> None:
    global _json_override, _stream_override
    _json_override = complete_json
    _stream_override = stream_tokens


def _strip_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


async def complete_json(system: str, user: str, *, timeout: float = 120.0) -> dict[str, Any]:
    if _json_override is not None:
        result = _json_override(system, user)
        if hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, dict):
            raise ApiError(502, "The model returned an unreadable result.")
        return result

    settings = get_settings()
    if not settings.openai_api_key:
        raise ApiError(502, "The language model is not configured.")

    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise ApiError(502, "The language model could not be reached.") from e
    if res.status_code >= 400:
        raise ApiError(502, "The language model rejected the request.")
    try:
        body = res.json()
        text = body["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_fences(text))
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise ApiError(502, "The model returned an unreadable result.") from e
    if not isinstance(parsed, dict):
        raise ApiError(502, "The model returned an unreadable result.")
    return parsed


async def stream_tokens(system: str, messages: list[dict[str, str]], *, timeout: float = 180.0) -> AsyncIterator[str]:
    if _stream_override is not None:
        async for chunk in _stream_override(system, messages):
            yield chunk
        return

    settings = get_settings()
    if not settings.openai_api_key:
        raise ApiError(502, "The language model is not configured.")

    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "temperature": 0.3,
        "stream": True,
        "messages": [{"role": "system", "content": system}, *messages],
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as res:
                if res.status_code >= 400:
                    await res.aread()
                    raise ApiError(502, "The language model rejected the request.")
                async for line in res.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data = line[5:].strip()
                    else:
                        continue
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0].get("delta", {}).get("content")
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        continue
                    if isinstance(delta, str) and delta:
                        yield delta
    except ApiError:
        raise
    except httpx.HTTPError as e:
        raise ApiError(502, "The language model could not be reached.") from e

"""CRLF-safe SSE helpers.

Legal-tool streams put the event name in the JSON `type` field (no `event:` line).
Chat streams use a real `event:` line. Both need `: heartbeat` comments so the
add-in's 120s idle timeout does not fire during a long model call.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

HEARTBEAT_EVERY_S = 15.0


def format_typed(payload: dict[str, Any]) -> str:
    """Legal-tool event: type lives inside the JSON."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def format_named(event: str, payload: dict[str, Any]) -> str:
    """Chat-style named SSE event."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def heartbeat() -> str:
    return ": heartbeat\n\n"


async def with_heartbeats(source: AsyncIterator[str], interval: float = HEARTBEAT_EVERY_S) -> AsyncIterator[str]:
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for item in source:
                await queue.put(item)
        finally:
            await queue.put(None)

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                yield heartbeat()
                continue
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


def sse_response(source: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        with_heartbeats(source),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

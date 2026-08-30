from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.security import CurrentUser, get_current_user
from app.models.schemas import ImprovePromptRequest, StreamChatRequest
from app.services import prompts
from app.services.llm import complete_json, stream_tokens
from app.services.sse import format_named, sse_response

router = APIRouter(tags=["chat"])

CONTEXT_CAP = 300_000


@router.post("/stream/chat")
async def stream_chat(
    body: StreamChatRequest,
    _user: CurrentUser = Depends(get_current_user),
):
    context = (body.context or "")[:CONTEXT_CAP]
    system = prompts.assistant_system(context)
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    async def events() -> AsyncIterator[str]:
        yield format_named("thinking", {"step": "generating", "message": "Writing the answer"})
        yield format_named("sources", {"sources": []})
        try:
            async for delta in stream_tokens(system, messages):
                yield format_named("chunk", {"content": delta})
        except ApiError as e:
            yield format_named("error", {"message": e.message})
            yield format_named("done", {})
            return
        except Exception:
            yield format_named("error", {"message": "The assistant could not respond."})
            yield format_named("done", {})
            return
        yield format_named("done", {})

    return sse_response(events())


@router.post("/chat/improve-prompt")
async def improve_chat(body: ImprovePromptRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.improve_prompt(body.prompt, "chat")
    return await complete_json(system, user)

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response

from app.core.errors import ApiError
from app.core.security import CurrentUser, get_current_user
from app.db.store import Store, get_store
from app.models.schemas import (
    DraftListItem,
    DraftReferenceOut,
    DraftResult,
    DraftRow,
    ExplainRequest,
    GenerateDraftRequest,
    GeneratedSection,
    ImprovePromptRequest,
    RewriteRequest,
)
from app.services import prompts
from app.services.docx_export import draft_to_docx_bytes
from app.services.llm import complete_json
from app.services.text_extract import extract_text, word_count

router = APIRouter(tags=["drafting"])


def _tiptap(title: str, sections: list[dict[str, str]]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": title.upper()}]}
    ]
    for s in sections:
        if s.get("title"):
            content.append(
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": s["title"]}]}
            )
        if s.get("content"):
            content.append({"type": "paragraph", "content": [{"type": "text", "text": s["content"]}]})
    return {"type": "doc", "content": content}


def _sections_from_raw(raw: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    items = raw.get("sections") if isinstance(raw.get("sections"), list) else []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        title = item.get("title") if isinstance(item.get("title"), str) else ""
        body = item.get("content") if isinstance(item.get("content"), str) else ""
        out.append({"id": f"s{i + 1}", "title": title, "content": body})
    return out


def _full_text(title: str, sections: list[dict[str, str]]) -> str:
    parts = [title.upper(), "", ""]
    for s in sections:
        parts.extend([s["title"], "", s["content"], ""])
    return "\n".join(parts)


def _result(draft_id: str, title: str, category: str, sections: list[dict[str, str]]) -> DraftResult:
    return DraftResult(
        draft_id=draft_id,
        title=title,
        category=category,
        full_text=_full_text(title, sections),
        sections=[GeneratedSection(id=s["id"], title=s["title"], content=s["content"]) for s in sections],
    )


async def _reference_text(store: Store, org_id: str, ids: list[str] | None) -> str:
    if not ids:
        return ""
    rows = await store.get_references(org_id, ids)
    return "\n\n".join(r.get("text") or "" for r in rows if r.get("text"))


async def _generate_sections(
    store: Store,
    org_id: str,
    body: GenerateDraftRequest,
) -> list[dict[str, str]]:
    refs = await _reference_text(store, org_id, body.reference_document_ids)
    system, user = prompts.draft_generate_prompt(
        body.category,
        body.title,
        body.tone or "balanced",
        body.governing_law_state or "",
        body.special_instructions or "",
        refs,
    )
    raw = await complete_json(system, user, timeout=180.0)
    return _sections_from_raw(raw)


@router.post("/drafting/clause/rewrite")
async def rewrite(body: RewriteRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.rewrite_prompt(
        body.clause_text, body.instruction, body.mode, body.tone, body.jurisdiction
    )
    return await complete_json(system, user)


@router.post("/drafting/clause/explain")
async def explain(body: ExplainRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.explain_prompt(body.clause_text, body.jurisdiction)
    return await complete_json(system, user)


@router.post("/drafting/improve-prompt")
async def improve_drafting(body: ImprovePromptRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.improve_prompt(body.prompt, "drafting")
    return await complete_json(system, user)


@router.post("/drafting/upload-reference", response_model=DraftReferenceOut)
async def upload_reference(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> DraftReferenceOut:
    data = await file.read()
    filename = file.filename or "reference.txt"
    text = extract_text(filename, data)
    wc = word_count(text)
    row = await store.save_reference(user.organization_id or "", user.user_id, filename, text, wc)
    return DraftReferenceOut(id=row["id"], file_name=row.get("file_name") or filename, word_count=wc)


@router.post("/drafting/generate", response_model=DraftResult)
async def generate_sync(
    body: GenerateDraftRequest,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> DraftResult:
    sections = await _generate_sections(store, user.organization_id or "", body)
    draft_id = str(uuid4())
    await store.create_draft(
        user.organization_id or "",
        user.user_id,
        {
            "id": draft_id,
            "title": body.title,
            "category": body.category,
            "content": _tiptap(body.title, sections),
            "generation_status": "completed",
            "generation_progress": {
                "status": "completed",
                "stepIndex": len(sections),
                "totalSteps": len(sections),
            },
        },
    )
    return _result(draft_id, body.title, body.category, sections)


@router.post("/drafting/generate/queue")
async def generate_queue(
    body: GenerateDraftRequest,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, str]:
    draft_id = str(uuid4())
    await store.create_draft(
        user.organization_id or "",
        user.user_id,
        {
            "id": draft_id,
            "title": body.title,
            "category": body.category,
            "generation_status": "running",
            "generation_progress": {"status": "running", "stepIndex": 0, "totalSteps": 1, "label": "Drafting"},
        },
    )
    org_id = user.organization_id or ""
    asyncio.create_task(_run_queued(store, org_id, draft_id, body))
    return {"draftId": draft_id, "status": "running"}


async def _run_queued(store: Store, org_id: str, draft_id: str, body: GenerateDraftRequest) -> None:
    try:
        sections = await _generate_sections(store, org_id, body)
        row = await store.get_draft(org_id, draft_id)
        if not row:
            return
        progress = row.get("generation_progress") or {}
        if isinstance(progress, dict) and progress.get("errorCode") == "CANCELLED":
            return
        if row.get("generation_status") == "failed":
            return
        await store.update_draft(
            org_id,
            draft_id,
            {
                "content": _tiptap(body.title, sections),
                "generation_status": "completed",
                "generation_progress": {
                    "status": "completed",
                    "stepIndex": len(sections),
                    "totalSteps": len(sections),
                },
                "generation_error": None,
            },
        )
    except Exception as e:
        try:
            await store.update_draft(
                org_id,
                draft_id,
                {
                    "generation_status": "failed",
                    "generation_error": str(e)[:500] or "Draft generation failed.",
                },
            )
        except ApiError:
            pass


@router.get("/drafting/drafts")
async def list_drafts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    rows = await store.list_drafts(user.organization_id or "", limit, offset)
    return [
        DraftListItem(
            id=r["id"],
            title=r.get("title") or "Untitled draft",
            category=r.get("category") or "custom",
            status=r.get("status") or "draft",
            version=r.get("version") or 1,
            source=r.get("source"),
            updated_at=r.get("updated_at"),
            generation_status=r.get("generation_status"),
        ).model_dump(by_alias=True)
        for r in rows
    ]


@router.get("/drafting/drafts/{draft_id}", response_model=DraftRow)
async def get_draft(
    draft_id: str,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> DraftRow:
    row = await store.get_draft(user.organization_id or "", draft_id)
    if not row:
        raise ApiError(404, "Draft not found.", "not_found")
    return DraftRow(
        id=row["id"],
        title=row.get("title") or "Untitled draft",
        category=row.get("category") or "custom",
        content=row.get("content"),
        metadata=row.get("metadata") or {},
        generation_status=row.get("generation_status"),
        generation_progress=row.get("generation_progress"),
        generation_error=row.get("generation_error"),
    )


@router.post("/drafting/drafts/{draft_id}/cancel")
async def cancel_draft(
    draft_id: str,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, bool]:
    row = await store.get_draft(user.organization_id or "", draft_id)
    if not row:
        return {"cancelled": False}
    if row.get("generation_status") not in ("running", "pending"):
        return {"cancelled": False}
    await store.update_draft(
        user.organization_id or "",
        draft_id,
        {
            "generation_status": "failed",
            "generation_progress": {"errorCode": "CANCELLED", "status": "failed"},
            "generation_error": "Cancelled",
        },
    )
    return {"cancelled": True}


@router.get("/drafting/drafts/{draft_id}/export")
async def export_draft(
    draft_id: str,
    format: str = Query("docx"),
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> Response:
    if format != "docx":
        raise ApiError(400, "Only docx export is supported.", "invalid")
    row = await store.get_draft(user.organization_id or "", draft_id)
    if not row:
        raise ApiError(404, "Draft not found.", "not_found")
    title = row.get("title") or "draft"
    data = draft_to_docx_bytes(title, row.get("content"))
    filename = f"{title.replace(' ', '_')}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

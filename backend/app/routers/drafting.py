from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response

from app.core.errors import ApiError
from app.core.security import CurrentUser, get_current_user
from app.db.store import Store, expire_stale_generation, get_store
from app.models.schemas import (
    ClauseCreate,
    ClauseOut,
    DetectEntitiesRequest,
    DraftListItem,
    DraftReferenceOut,
    DraftResult,
    DraftRow,
    EditDocumentRequest,
    ExplainRequest,
    GenerateDraftRequest,
    GeneratedSection,
    ImprovePromptRequest,
    ImportDraftRequest,
    ReconcileRequest,
    RewriteRequest,
)
from app.services import prompts
from app.services.docx_export import draft_to_docx_bytes
from app.services.grounding import normalize_redline
from app.services.llm import complete_json
from app.services.sse import format_named, sse_response
from app.services.text_extract import extract_text, word_count

MAX_DOCUMENT_CHARS = 200_000


def _cap(text: str) -> None:
    if len(text) > MAX_DOCUMENT_CHARS:
        raise ApiError(
            413,
            "This document is too long to review in full. Select a section instead.",
            "document_too_large",
            extra={"limit_chars": MAX_DOCUMENT_CHARS},
        )


def _clause_out(row: dict[str, Any]) -> dict[str, Any]:
    return ClauseOut(
        id=row["id"],
        name=row.get("name") or "Clause",
        clause_type=row.get("clause_type") or "custom",
        content=row.get("content") or "",
        jurisdiction=row.get("jurisdiction") or "US",
        tone=row.get("tone") or "balanced",
        applicable_acts=row.get("applicable_acts") or [],
        tags=row.get("tags") or [],
        applicable_categories=row.get("applicable_categories"),
        source=row.get("source") or "user",
        is_system=bool(row.get("is_system")),
        created_at=str(row.get("created_at")) if row.get("created_at") else None,
    ).model_dump(by_alias=True)

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


@router.post("/drafting/import")
async def import_draft(
    body: ImportDraftRequest,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, str]:
    """Persist a reviewed or prepared document as a draft (Save to HakiChain)."""
    title = body.title or "Imported document"
    content = body.content if isinstance(body.content, dict) else _tiptap(title, [])
    row = await store.create_draft(
        user.organization_id or "",
        user.user_id,
        {
            "title": title,
            "category": body.category or "custom",
            "content": content,
            "source": "imported",
            "metadata": {"redlines": body.redlines or [], "matter_id": body.matter_id},
            "generation_status": "completed",
        },
    )
    return {"draftId": row["id"], "title": row.get("title") or title, "category": row.get("category") or "custom"}


@router.post("/drafting/drafts/{draft_id}/save-to-matter")
async def save_draft_to_matter(
    draft_id: str,
    matterId: str = Query(""),
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, bool]:
    row = await store.get_draft(user.organization_id or "", draft_id)
    if not row:
        raise ApiError(404, "Draft not found.", "not_found")
    # Matters are empty in the MVP. Accept the call so the pane does not error.
    _ = matterId
    return {"ok": True}


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
    row = await expire_stale_generation(store, user.organization_id or "", row)
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


@router.post("/drafting/drafts/{draft_id}/approvals")
async def record_approval(
    draft_id: str,
    _user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> None:
    row = await store.get_draft(_user.organization_id or "", draft_id)
    if not row:
        raise ApiError(404, "Draft not found.", "not_found")
    raise ApiError(
        404,
        "Authority-enforced sign-off is not available in this build. Use the in-file attestation.",
        "not_found",
    )


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


@router.get("/drafting/clauses")
async def list_clauses(
    clauseType: str | None = None,
    jurisdiction: str | None = None,
    tone: str | None = None,
    source: str | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    rows = await store.list_clauses(
        user.organization_id or "",
        {
            "clause_type": clauseType,
            "jurisdiction": jurisdiction,
            "tone": tone,
            "source": source,
            "limit": limit,
            "offset": offset,
        },
    )
    return [_clause_out(r) for r in rows]


@router.post("/drafting/clauses")
async def create_clause(
    body: ClauseCreate,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    clause_type = body.clause_type or body.clauseType or "custom"
    row = await store.create_clause(
        user.organization_id or "",
        user.user_id,
        {
            "name": body.name,
            "clause_type": clause_type,
            "content": body.content,
            "jurisdiction": body.jurisdiction,
            "tone": body.tone,
            "tags": body.tags,
        },
    )
    return _clause_out(row)


@router.delete("/drafting/clauses/{clause_id}")
async def delete_clause(
    clause_id: str,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> Response:
    await store.delete_clause(user.organization_id or "", clause_id)
    return Response(status_code=204)


@router.post("/drafting/extract-text")
async def extract_text_route(
    file: UploadFile = File(...),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    data = await file.read()
    filename = file.filename or "document.txt"
    text = extract_text(filename, data)
    return {"text": text, "chars": len(text), "truncated": False, "filename": filename}


@router.post("/drafting/extract-clause")
async def extract_clause_route(
    file: UploadFile = File(...),
    clause: str = Form(""),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    data = await file.read()
    filename = file.filename or "document.txt"
    text = extract_text(filename, data)
    _cap(text)
    system, user = prompts.extract_clause_prompt(clause, text)
    raw = await complete_json(system, user)
    found = raw.get("found") is True
    extracted = raw.get("text") if isinstance(raw.get("text"), str) else ""
    if extracted and extracted not in text:
        found = False
        extracted = ""
    return {
        "found": found,
        "label": raw.get("label") if isinstance(raw.get("label"), str) else clause,
        "text": extracted,
    }


@router.post("/drafting/fill-from-reference")
async def fill_from_reference(
    file: UploadFile = File(...),
    placeholders: str = Form("[]"),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    data = await file.read()
    filename = file.filename or "reference.txt"
    text = extract_text(filename, data)
    _cap(text)
    try:
        names = json.loads(placeholders)
    except json.JSONDecodeError:
        names = []
    if not isinstance(names, list):
        names = []
    names = [n for n in names if isinstance(n, str)]
    system, user = prompts.fill_prompt(names, text)
    raw = await complete_json(system, user)
    fills = []
    items = raw.get("fills") if isinstance(raw.get("fills"), list) else []
    for i, name in enumerate(names):
        item = items[i] if i < len(items) and isinstance(items[i], dict) else {}
        quote = item.get("quote") if isinstance(item.get("quote"), str) else ""
        value = item.get("value") if isinstance(item.get("value"), str) else ""
        found = item.get("found") is True and bool(quote) and quote in text
        fills.append(
            {
                "placeholder": name,
                "found": found,
                "value": value if found else "",
                "quote": quote if found else "",
            }
        )
    return {"fills": fills, "referenceChars": len(text), "truncated": False}


@router.post("/drafting/reconcile-terms")
async def reconcile_terms(
    body: ReconcileRequest,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _cap(body.destination_text)
    system, user = prompts.reconcile_prompt(body.clause_text, body.destination_text)
    return await complete_json(system, user)


@router.post("/redaction/detect-entities")
async def detect_entities(
    body: DetectEntitiesRequest,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _cap(body.document_text)
    system, user = prompts.redact_prompt(body.document_text)
    raw = await complete_json(system, user)
    entities = []
    for item in raw.get("entities") if isinstance(raw.get("entities"), list) else []:
        if not isinstance(item, dict):
            continue
        text = item.get("text") if isinstance(item.get("text"), str) else ""
        if text and text in body.document_text:
            entities.append(
                {
                    "category": item.get("category") if isinstance(item.get("category"), str) else "person",
                    "text": text,
                }
            )
    return {"entities": entities}


def _ground_edits(document: str, raw: dict[str, Any]) -> dict[str, Any]:
    edits = []
    for item in raw.get("edits") if isinstance(raw.get("edits"), list) else []:
        if not isinstance(item, dict):
            continue
        grounded = normalize_redline(
            {
                "clauseName": item.get("label") or item.get("clauseName"),
                "currentLanguage": item.get("currentLanguage") or item.get("current_language"),
                "proposedLanguage": item.get("proposedLanguage") or item.get("proposed_language"),
                "rationale": item.get("rationale"),
                "fallbackPosition": item.get("fallbackPosition") or item.get("fallback_position"),
                "nature": item.get("nature"),
                "grounding": item.get("grounding"),
            },
            document,
        )
        edits.append(
            {
                "label": item.get("label") if isinstance(item.get("label"), str) else grounded["clauseName"],
                "sectionReference": item.get("sectionReference")
                if isinstance(item.get("sectionReference"), str)
                else grounded.get("sectionReference") or "",
                "currentLanguage": grounded["currentLanguage"],
                "proposedLanguage": grounded["proposedLanguage"],
                "rationale": grounded["rationale"],
                "fallbackPosition": grounded.get("fallbackPosition"),
                "grounding": grounded["grounding"],
                "nature": grounded.get("nature"),
            }
        )
    return {
        "overview": raw.get("overview") if isinstance(raw.get("overview"), str) else "",
        "edits": edits,
        "summary": raw.get("summary") if isinstance(raw.get("summary"), str) else "",
    }


async def _run_edit(body: EditDocumentRequest) -> dict[str, Any]:
    _cap(body.document_text)
    prior = []
    for e in body.prior_edits or []:
        if isinstance(e, dict):
            prior.append(
                {
                    "label": str(e.get("label") or ""),
                    "currentLanguage": str(e.get("currentLanguage") or e.get("current_language") or ""),
                    "proposedLanguage": str(e.get("proposedLanguage") or e.get("proposed_language") or ""),
                }
            )
    system, user = prompts.edit_document_prompt(
        body.document_text,
        body.instruction,
        body.contract_type,
        body.prior_instructions or [],
        prior,
    )
    raw = await complete_json(system, user)
    return _ground_edits(body.document_text, raw)


@router.post("/drafting/edit-document")
async def edit_document(
    body: EditDocumentRequest,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await _run_edit(body)


@router.post("/drafting/edit-document/stream")
async def edit_document_stream(
    body: EditDocumentRequest,
    _user: CurrentUser = Depends(get_current_user),
):
    async def events() -> AsyncIterator[str]:
        yield format_named("meta", {"sections": 0})
        try:
            result = await _run_edit(body)
        except ApiError as e:
            yield format_named("error", {"message": e.message})
            yield format_named("done", {})
            return
        except Exception:
            yield format_named("error", {"message": "The edit could not be completed."})
            yield format_named("done", {})
            return
        for edit in result["edits"]:
            yield format_named("edit", {"edit": edit})
        yield format_named(
            "summary",
            {"overview": result["overview"], "summary": result["summary"], "count": len(result["edits"])},
        )
        yield format_named("done", {})

    return sse_response(events())

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.security import CurrentUser, get_current_user
from app.db.store import Store, get_store
from app.models.schemas import (
    ClassifyRequest,
    ClassifyResponse,
    ClauseFixRequest,
    ComplianceRequest,
    ContractReviewRequest,
    GuidelinesRequest,
    ImprovePromptRequest,
    NdaTriageRequest,
    PlainEnglishRequest,
    PlaybookFitRequest,
    RiskRequest,
)
from app.services import prompts
from app.services.grounding import compute_approval_gate, normalize_redline, shape_review
from app.services.llm import complete_json
from app.services.sse import format_named, format_typed, sse_response

router = APIRouter(tags=["legal-tools"])

MAX_DOCUMENT_CHARS = 200_000


def _cap(text: str) -> None:
    if len(text) > MAX_DOCUMENT_CHARS:
        raise ApiError(
            413,
            "This document is too long to review in full. Select a section instead.",
            "document_too_large",
            extra={"limit_chars": MAX_DOCUMENT_CHARS},
        )


@router.post("/legal-tools/contract-review/classify", response_model=ClassifyResponse)
async def classify(
    body: ClassifyRequest,
    _user: CurrentUser = Depends(get_current_user),
) -> ClassifyResponse:
    system, user = prompts.classify_contract_prompt(body.document_text)
    raw = await complete_json(system, user)
    ct = raw.get("contractType")
    return ClassifyResponse(
        contract_type=ct if isinstance(ct, str) else None,
        confidence=raw.get("confidence") if isinstance(raw.get("confidence"), (int, float)) else 0.5,
    )


@router.post("/legal-tools/contract-review/stream")
async def review_stream(
    body: ContractReviewRequest,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
):
    _cap(body.document_text)
    analysis_id = str(uuid4())
    await store.save_analysis(user.organization_id or "", user.user_id, analysis_id, None)

    async def events() -> AsyncIterator[str]:
        yield format_typed({"type": "init", "totalSteps": 3, "analysisId": analysis_id})
        yield format_typed({"type": "progress", "stepIndex": 0, "label": "Reading the contract"})
        playbook_text = ""
        if body.playbook_id:
            row = await store.get_playbook(user.organization_id or "", body.playbook_id)
            if row:
                playbook_text = prompts.playbook_block(row.get("positions") or {})
        yield format_typed({"type": "progress", "stepIndex": 1, "label": "Reviewing clauses"})
        try:
            system, prompt_user = prompts.contract_review_prompt(
                body.document_text,
                body.contract_type,
                body.user_side,
                body.markup_level or "standard",
                body.paper_side,
                body.review_instructions,
                playbook_text,
            )
            raw = await complete_json(system, prompt_user, timeout=180.0)
            review = shape_review(
                raw,
                body.document_text,
                analysis_id,
                body.contract_type or None,
                body.user_side or None,
            )
            await store.save_analysis(user.organization_id or "", user.user_id, analysis_id, review)
            yield format_typed({"type": "progress", "stepIndex": 2, "label": "Preparing redlines"})
            yield format_typed({"type": "result", "data": review})
        except ApiError as e:
            yield format_typed({"type": "error", "message": e.message})
        except Exception:
            yield format_typed({"type": "error", "message": "The review failed."})
        yield format_typed({"type": "done"})

    return sse_response(events())


@router.get("/legal-tools/analyses/{analysis_id}")
async def get_analysis(
    analysis_id: str,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    row = await store.get_analysis(user.organization_id or "", analysis_id)
    if not row:
        raise ApiError(404, "Analysis not found.", "not_found")
    return {"result": row.get("result")}


@router.post("/legal-tools/contract-review/redline/draft-fix")
async def draft_fix(
    body: ClauseFixRequest,
    _user: CurrentUser = Depends(get_current_user),
):
    async def events() -> AsyncIterator[str]:
        yield format_named(
            "thinking",
            {"step": "draft", "message": "Drafting a stronger clause", "progress": 0.4},
        )
        try:
            system, prompt_user = prompts.clause_fix_prompt(
                body.clause_name,
                body.current_language,
                body.jurisdiction or "US",
            )
            raw = await complete_json(system, prompt_user)
            proposed = raw.get("proposedLanguage") if isinstance(raw.get("proposedLanguage"), str) else ""
            current = body.current_language
            if not proposed:
                proposed = current
            redline = normalize_redline(
                {
                    "clauseName": body.clause_name,
                    "currentLanguage": current,
                    "proposedLanguage": proposed,
                    "rationale": raw.get("rationale") or "",
                    "fallbackPosition": raw.get("fallbackPosition"),
                    "isDealBreaker": False,
                    "nature": "substantive",
                },
                current,
            )
            no_change = raw.get("noChangeNeeded") is True or proposed.strip() == current.strip()
            yield format_named(
                "result",
                {
                    "type": "result",
                    "redline": redline,
                    "approvalGate": compute_approval_gate([redline]),
                    "noChangeNeeded": no_change,
                },
            )
        except ApiError as e:
            yield format_named("error", {"message": e.message})
        except Exception:
            yield format_named("error", {"message": "The fix could not be drafted."})
        yield format_named("done", {})

    return sse_response(events())


@router.post("/legal-tools/plain-english")
async def plain_english(body: PlainEnglishRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.plain_english_prompt(body.text)
    return await complete_json(system, user)


@router.post("/legal-tools/risk-assessment")
async def risk_assessment(body: RiskRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.risk_prompt(body.document_text, body.risk_category)
    return await complete_json(system, user)


@router.post("/legal-tools/compliance-check")
async def compliance_check(body: ComplianceRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.compliance_prompt(body.document_text, body.regulation_type, body.document_category)
    return await complete_json(system, user)


@router.post("/legal-tools/nda-triage")
async def nda_triage(body: NdaTriageRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.nda_triage_prompt(
        body.document_text,
        body.counterparty_name or "",
        body.business_context or "",
    )
    raw = await complete_json(system, user)
    classification = raw.get("classification")
    return {
        "id": str(uuid4()),
        **raw,
        "effectiveClassification": classification if isinstance(classification, str) else None,
    }


@router.post("/legal-tools/improve-prompt")
async def improve_legal_tool(body: ImprovePromptRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.improve_prompt(body.prompt, "legalTool")
    return await complete_json(system, user)


@router.post("/guidelines/check")
async def guidelines_check(body: GuidelinesRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    system, user = prompts.guidelines_prompt(body.document_text, body.guidelines)
    return await complete_json(system, user)


@router.post("/playbook-fit/check")
async def playbook_fit(body: PlaybookFitRequest, _user: CurrentUser = Depends(get_current_user)) -> dict:
    positions = {k: v.model_dump(by_alias=True) for k, v in body.positions.items()}
    system, user = prompts.playbook_fit_prompt(body.document_text, positions)
    return await complete_json(system, user)

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.errors import ApiError
from app.core.security import CurrentUser, get_current_user
from app.db.store import Store, get_store
from app.models.schemas import LearningApply, PlaybookCreate, PlaybookList, PlaybookOut
from app.services import prompts
from app.services.llm import complete_json
from app.services.text_extract import extract_text

router = APIRouter(tags=["playbooks"])


def _out(row: dict[str, Any]) -> PlaybookOut:
    return PlaybookOut(
        id=row["id"],
        name=row.get("name") or "Playbook",
        contract_type=row.get("contract_type") or "custom",
        is_default=bool(row.get("is_default")),
        updated_at=row.get("updated_at"),
        created_at=row.get("created_at"),
        organization_id=row.get("organization_id"),
        positions=row.get("positions") or {},
    )


@router.get("/legal-tools/playbooks", response_model=PlaybookList)
async def list_playbooks(
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> PlaybookList:
    rows = await store.list_playbooks(user.organization_id or "")
    playbooks = [_out(r) for r in rows]
    return PlaybookList(playbooks=playbooks, total=len(playbooks))


@router.post("/legal-tools/playbooks")
async def create_playbook(
    body: PlaybookCreate,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, str]:
    row = await store.create_playbook(
        user.organization_id or "",
        user.user_id,
        {
            "name": body.name,
            "contract_type": body.contract_type,
            "positions": body.positions,
        },
    )
    return {"id": row["id"]}


@router.post("/legal-tools/playbooks/extract-from-docx")
async def extract_playbook(
    text: str = Form(""),
    contract_type: str = Form("auto"),
    file: UploadFile | None = File(None),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    source_text = text
    if (not source_text.strip()) and file is not None:
        data = await file.read()
        source_text = extract_text(file.filename or "playbook.docx", data)
    system, user = prompts.playbook_extract_prompt(source_text)
    raw = await complete_json(system, user)
    positions = raw.get("positions") if isinstance(raw.get("positions"), dict) else {}
    detected = raw.get("contractType") if isinstance(raw.get("contractType"), str) else ""
    return {
        "positions": positions,
        "extracted_count": len(positions),
        "contract_type": detected or ("" if contract_type == "auto" else contract_type),
        "jurisdiction": "US",
        "source": "text",
    }


@router.post("/legal-tools/playbooks/{playbook_id}/learning/apply")
async def apply_learning(
    playbook_id: str,
    body: LearningApply,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict:
    existing = await store.get_playbook(user.organization_id or "", playbook_id)
    if not existing:
        raise ApiError(404, "Playbook not found.", "not_found")
    positions = dict(existing.get("positions") or {})
    key = body.clause_type
    pos = dict(positions.get(key) or {})
    ladder = list(pos.get("fallbackLadder") or pos.get("fallback_ladder") or [])
    if body.mode == "add_fallback" and body.text:
        ladder.append(body.text[:8000])
    pos["fallbackLadder"] = ladder
    if "standardPosition" not in pos and "standard_position" not in pos:
        pos["standardPosition"] = pos.get("standardPosition") or ""
    positions[key] = pos
    await store.update_playbook(user.organization_id or "", playbook_id, {"positions": positions})
    return {}

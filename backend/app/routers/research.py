"""Honest empty research / authority responses. Do not invent case law.

Citation-style (Bluebook format) is a real LLM check and lives here because
the add-in calls POST /api/v1/us/citation-style.
"""

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, get_current_user
from app.models.schemas import CitationStyleRequest
from app.services import prompts
from app.services.llm import complete_json

router = APIRouter(tags=["research"])


@router.post("/us/citation-style")
async def citation_style(
    body: CitationStyleRequest,
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    system, user = prompts.citation_style_prompt(body.citations)
    return await complete_json(system, user)


@router.get("/us/citation-lookup")
async def citation_lookup(_user: CurrentUser = Depends(get_current_user)) -> list:
    return []


@router.get("/us/case/{cluster_id}/citations")
async def case_citations(cluster_id: str, _user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"authority_count": 0, "cited_by_count": 0}


@router.get("/us/cases/{cluster_id}/brief")
async def case_brief(cluster_id: str, _user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"brief": "", "fromCache": False}


@router.get("/us-statutes/resolve")
async def statute_resolve(_user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"found": False}


@router.post("/us-statutes/search")
async def statute_search(_user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"results": [], "total": 0, "page": 1, "pageSize": 20}


@router.get("/us-statutes/section/{act_id}/body")
async def statute_body(act_id: str, _user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"actId": act_id, "html": None, "plain": None, "available": False, "note": None}


@router.post("/us-statutes/section/{act_id}/ask")
async def statute_ask(act_id: str, _user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"answer": "", "citation": None, "confidence": "low", "notInSection": True}


@router.post("/citation-status/batch")
async def citation_status_batch(_user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"results": []}

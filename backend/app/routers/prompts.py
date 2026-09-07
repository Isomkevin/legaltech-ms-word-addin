from fastapi import APIRouter, Depends, Response

from app.core.security import CurrentUser, get_current_user
from app.core.errors import ApiError
from app.db.store import Store, get_store
from app.models.schemas import PromptIn, PromptList, PromptOut, PromptPatch

router = APIRouter(tags=["prompts"])


def _out(row: dict, user_id: str) -> PromptOut:
    return PromptOut(
        id=row["id"],
        user_id=row.get("user_id") or "",
        organization_id=row.get("organization_id"),
        title=row.get("title") or "",
        body=row.get("body") or "",
        scope=row.get("scope") or "private",
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        is_owner=row.get("user_id") == user_id,
    )


@router.get("/prompts", response_model=PromptList)
async def list_prompts(
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> PromptList:
    rows = await store.list_prompts(user.organization_id or "", user.user_id)
    return PromptList(prompts=[_out(r, user.user_id) for r in rows])


@router.post("/prompts", response_model=PromptOut)
async def create_prompt(
    body: PromptIn,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> PromptOut:
    row = await store.create_prompt(
        user.organization_id or "",
        user.user_id,
        {"title": body.title, "body": body.body, "scope": body.scope},
    )
    return _out(row, user.user_id)


@router.patch("/prompts/{prompt_id}", response_model=PromptOut)
async def update_prompt(
    prompt_id: str,
    body: PromptPatch,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> PromptOut:
    existing = await store.get_prompt(user.organization_id or "", prompt_id)
    if not existing:
        raise ApiError(404, "Prompt not found.", "not_found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    row = await store.update_prompt(user.organization_id or "", prompt_id, patch)
    return _out(row, user.user_id)


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> Response:
    await store.delete_prompt(user.organization_id or "", prompt_id)
    return Response(status_code=204)

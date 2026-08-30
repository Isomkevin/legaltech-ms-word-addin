from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, get_current_user_no_org
from app.db.store import Store, get_store
from app.models.schemas import Me

router = APIRouter(tags=["auth"])


@router.get("/auth/me", response_model=Me)
async def me(
    user: CurrentUser = Depends(get_current_user_no_org),
    store: Store = Depends(get_store),
) -> Me:
    org_id = user.organization_id
    if not org_id:
        org_id = await store.ensure_personal_org(user.user_id, user.full_name, user.email)
    return Me(
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name,
        organization_id=org_id,
        initialized=True,
    )

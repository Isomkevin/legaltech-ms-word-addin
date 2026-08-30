from fastapi import APIRouter, Depends, Response

from app.core.security import CurrentUser, get_current_user
from app.models.schemas import QuotaSummary, QuotaUsage, UsageMetric

router = APIRouter(tags=["shell"])

_UNLIMITED = UsageMetric(current=0, limit=100_000, percentage=0)


@router.get("/quotas/summary", response_model=QuotaSummary)
async def quotas_summary(_user: CurrentUser = Depends(get_current_user)) -> QuotaSummary:
    return QuotaSummary(
        tier="mvp",
        tier_name="HakiChain AI",
        usage=QuotaUsage(
            monthly_messages=_UNLIMITED,
            monthly_deep_searches=_UNLIMITED,
            monthly_legal_tool_uses=_UNLIMITED,
            monthly_full_drafts=_UNLIMITED,
        ),
    )


@router.get("/matters")
async def list_matters(_user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"matters": [], "total": 0}


@router.get("/clients")
async def list_clients(_user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"clients": [], "total": 0}


@router.post("/redline-feedback/feedback")
async def redline_feedback(_user: CurrentUser = Depends(get_current_user)) -> dict:
    return {}


@router.post("/telemetry/ping")
async def telemetry_ping() -> Response:
    return Response(status_code=204)

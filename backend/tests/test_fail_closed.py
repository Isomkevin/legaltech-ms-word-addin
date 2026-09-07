from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import Settings
from app.db.store import MemoryStore, expire_stale_generation, require_supabase_or_raise


def test_require_supabase_raises_without_credentials():
    settings = Settings(
        require_supabase=True,
        supabase_url="",
        supabase_service_role_key="",
    )
    assert settings.has_supabase is False
    assert settings.require_supabase is True


def test_require_supabase_or_raise_fails_closed(monkeypatch):
    monkeypatch.setenv("REQUIRE_SUPABASE", "true")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="REQUIRE_SUPABASE"):
        require_supabase_or_raise()


def test_require_supabase_or_raise_ok_when_flag_off(monkeypatch):
    monkeypatch.setenv("REQUIRE_SUPABASE", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    require_supabase_or_raise()


def test_health_is_cheap(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ready_ok_without_require_supabase(client):
    res = client.get("/health/ready")
    assert res.status_code == 200


def test_ready_503_when_require_supabase(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_SUPABASE", "true")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    res = client.get("/health/ready")
    assert res.status_code == 503
    assert res.json()["status"] == "not_ready"


@pytest.mark.asyncio
async def test_stale_queued_draft_is_marked_failed():
    store = MemoryStore()
    org = "org-1"
    row = await store.create_draft(
        org,
        "user-1",
        {
            "id": "draft-stale",
            "title": "Stale",
            "document_type": "nda",
            "generation_status": "running",
        },
    )
    stale = {
        **row,
        "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
    }
    updated = await expire_stale_generation(store, org, stale)
    assert updated["generation_status"] == "failed"
    assert updated.get("generation_error")

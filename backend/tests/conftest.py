from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["SUPABASE_JWT_SECRET"] = "test-secret-at-least-32-chars-long!!"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
os.environ["CORS_ORIGINS"] = "https://localhost:3000"
os.environ["OPENAI_API_KEY"] = ""

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.store import MemoryStore, reset_store  # noqa: E402
from app.main import app  # noqa: E402
from app.services.llm import set_llm_overrides  # noqa: E402

get_settings.cache_clear()

JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]


def make_token(
    sub: str = "11111111-1111-1111-1111-111111111111",
    email: str = "ada@hakichain.test",
    name: str = "Ada Lawyer",
    expired: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    return jwt.encode(
        {
            "sub": sub,
            "email": email,
            "user_metadata": {"full_name": name},
            "aud": "authenticated",
            "role": "authenticated",
            "exp": exp,
            "iat": now,
        },
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture(autouse=True)
def _isolated_state():
    reset_store(MemoryStore())
    set_llm_overrides()
    yield
    set_llm_overrides()
    reset_store(MemoryStore())


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}

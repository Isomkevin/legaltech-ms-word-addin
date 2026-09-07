"""Optional live smoke. Not in default pytest. Requires SMOKE_JWT + SMOKE_API."""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.live

API = os.environ.get("SMOKE_API", "http://localhost:8000")
JWT = os.environ.get("SMOKE_JWT", "")


def test_live_health():
    res = httpx.get(f"{API}/health", timeout=10.0)
    assert res.status_code == 200


def test_live_me_and_review_stream():
    if not JWT:
        pytest.skip("SMOKE_JWT not set")
    headers = {"Authorization": f"Bearer {JWT}"}
    me = httpx.get(f"{API}/api/v1/auth/me", headers=headers, timeout=20.0)
    assert me.status_code == 200, me.text
    with httpx.stream(
        "POST",
        f"{API}/api/v1/legal-tools/contract-review/stream",
        headers=headers,
        json={"documentText": "The term is one year. Confidentiality survives indefinitely.", "contractType": "nda"},
        timeout=180.0,
    ) as res:
        assert res.status_code == 200
        body = "".join(res.iter_text())
    assert "done" in body
    assert "result" in body or "error" in body

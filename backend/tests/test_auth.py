from tests.conftest import make_token


def test_me_requires_bearer(client):
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401
    body = res.json()
    assert body["detail"]["error_code"] == "unauthorized"


def test_me_rejects_expired_token(client):
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {make_token(expired=True)}"})
    assert res.status_code == 401


def test_me_provisions_personal_org(client, auth_header):
    res = client.get("/api/v1/auth/me", headers=auth_header)
    assert res.status_code == 200
    body = res.json()
    assert body["userId"] == "11111111-1111-1111-1111-111111111111"
    assert body["email"] == "ada@hakichain.test"
    assert body["fullName"] == "Ada Lawyer"
    assert body["initialized"] is True
    assert body["organizationId"]


def test_forged_org_header_is_401(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    res = client.get(
        "/api/v1/quotas/summary",
        headers={**auth_header, "X-Organization-ID": "00000000-0000-0000-0000-000000000000"},
    )
    assert res.status_code == 401


def test_quotas_summary_is_generous(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    res = client.get("/api/v1/quotas/summary", headers=auth_header)
    assert res.status_code == 200
    body = res.json()
    assert body["tierName"]
    assert body["usage"]["monthlyLegalToolUses"]["limit"] >= 1000


def test_matters_and_clients_empty(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    matters = client.get("/api/v1/matters", headers=auth_header).json()
    clients = client.get("/api/v1/clients", headers=auth_header).json()
    assert matters == {"matters": [], "total": 0}
    assert clients == {"clients": [], "total": 0}


def test_research_stubs_do_not_invent_authorities(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    lookup = client.get("/api/v1/us/citation-lookup?citation=123%20U.S.%201", headers=auth_header)
    assert lookup.status_code == 200
    assert lookup.json() == []
    resolve = client.get("/api/v1/us-statutes/resolve?q=18%20USC%201030", headers=auth_header)
    assert resolve.json()["found"] is False

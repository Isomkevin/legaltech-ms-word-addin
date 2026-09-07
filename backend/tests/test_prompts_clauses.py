from tests.conftest import make_token


def _auth(client, token=None):
    headers = {"Authorization": f"Bearer {token or make_token()}"}
    client.get("/api/v1/auth/me", headers=headers)
    return headers


def test_prompts_crud_and_is_owner(client):
    headers = _auth(client)
    created = client.post(
        "/api/v1/prompts",
        headers=headers,
        json={"title": "NDA open", "body": "Review this NDA", "scope": "private"},
    )
    assert created.status_code == 200
    row = created.json()
    assert row["isOwner"] is True
    assert row["title"] == "NDA open"

    listed = client.get("/api/v1/prompts", headers=headers).json()
    assert listed["prompts"][0]["id"] == row["id"]

    patched = client.patch(
        f"/api/v1/prompts/{row['id']}",
        headers=headers,
        json={"title": "NDA open (v2)"},
    )
    assert patched.json()["title"] == "NDA open (v2)"

    deleted = client.delete(f"/api/v1/prompts/{row['id']}", headers=headers)
    assert deleted.status_code == 204
    missing = client.delete("/api/v1/prompts/does-not-exist", headers=headers)
    assert missing.status_code == 404


def test_prompts_org_isolation(client):
    ada = _auth(client, make_token(sub="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="ada@t.test"))
    bob = _auth(client, make_token(sub="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", email="bob@t.test", name="Bob"))
    client.post("/api/v1/prompts", headers=ada, json={"title": "Ada only", "body": "x", "scope": "org"})
    listed = client.get("/api/v1/prompts", headers=bob).json()
    assert all(p["title"] != "Ada only" for p in listed["prompts"])


def test_clauses_accept_snake_and_camel(client):
    headers = _auth(client)
    a = client.post(
        "/api/v1/drafting/clauses",
        headers=headers,
        json={"name": "Term", "clause_type": "term", "content": "The Term is one year."},
    )
    b = client.post(
        "/api/v1/drafting/clauses",
        headers=headers,
        json={"name": "Conf", "clauseType": "confidentiality", "content": "Keep secret."},
    )
    assert a.status_code == 200
    assert a.json()["clauseType"] == "term"
    assert b.json()["clauseType"] == "confidentiality"
    listed = client.get("/api/v1/drafting/clauses", headers=headers)
    assert listed.status_code == 200
    assert isinstance(listed.json(), list)
    assert len(listed.json()) == 2
    deleted = client.delete(f"/api/v1/drafting/clauses/{a.json()['id']}", headers=headers)
    assert deleted.status_code == 204


def test_prompts_require_auth(client):
    assert client.get("/api/v1/prompts").status_code == 401
    assert client.get("/api/v1/drafting/clauses").status_code == 401

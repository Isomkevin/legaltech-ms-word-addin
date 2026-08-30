from app.services.llm import set_llm_overrides


def test_first_list_seeds_starter_playbooks(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    res = client.get("/api/v1/legal-tools/playbooks", headers=auth_header)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 3
    names = {p["name"] for p in body["playbooks"]}
    assert "Mutual NDA (starter)" in names
    first = body["playbooks"][0]
    assert "positions" in first
    assert first["contractType"]


def test_learning_apply_appends_one_fallback(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    listed = client.get("/api/v1/legal-tools/playbooks", headers=auth_header).json()
    nda = next(p for p in listed["playbooks"] if p["contractType"] == "nda")
    res = client.post(
        f"/api/v1/legal-tools/playbooks/{nda['id']}/learning/apply",
        headers=auth_header,
        json={"clauseType": "permitted_use", "text": "Use only for diligence.", "mode": "add_fallback"},
    )
    assert res.status_code == 200
    again = client.get("/api/v1/legal-tools/playbooks", headers=auth_header).json()
    updated = next(p for p in again["playbooks"] if p["id"] == nda["id"])
    ladder = updated["positions"]["permitted_use"]["fallbackLadder"]
    assert "Use only for diligence." in ladder


def test_create_playbook_returns_id(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    res = client.post(
        "/api/v1/legal-tools/playbooks",
        headers=auth_header,
        json={"name": "Custom MSA", "contractType": "msa", "positions": {}},
    )
    assert res.status_code == 200
    assert res.json()["id"]


def test_classify_uses_llm_override(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    set_llm_overrides(complete_json=lambda *_: {"contractType": "nda", "confidence": 0.9})
    res = client.post(
        "/api/v1/legal-tools/contract-review/classify",
        headers=auth_header,
        json={"documentText": "This mutual nondisclosure agreement..."},
    )
    assert res.status_code == 200
    assert res.json()["contractType"] == "nda"
    assert res.json()["confidence"] == 0.9

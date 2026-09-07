from app.services.llm import set_llm_overrides


def test_extract_text_and_tools(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    files = {"file": ("note.txt", b"Alice works at Acme in Boston.", "text/plain")}
    extracted = client.post("/api/v1/drafting/extract-text", headers=auth_header, files=files)
    assert extracted.status_code == 200
    assert "Alice" in extracted.json()["text"]

    set_llm_overrides(
        complete_json=lambda _s, _u, **_k: {"found": True, "label": "Parties", "text": "Alice works at Acme in Boston."}
    )
    clause = client.post(
        "/api/v1/drafting/extract-clause",
        headers=auth_header,
        files={"file": ("note.txt", b"Alice works at Acme in Boston.", "text/plain")},
        data={"clause": "Parties"},
    )
    assert clause.status_code == 200
    assert clause.json()["found"] is True

    set_llm_overrides(
        complete_json=lambda _s, _u, **_k: {
            "fills": [{"placeholder": "Party", "found": True, "value": "Alice", "quote": "Alice"}]
        }
    )
    filled = client.post(
        "/api/v1/drafting/fill-from-reference",
        headers=auth_header,
        files={"file": ("ref.txt", b"Alice signed.", "text/plain")},
        data={"placeholders": '["Party"]'},
    )
    assert filled.status_code == 200
    assert filled.json()["fills"][0]["found"] is True

    set_llm_overrides(
        complete_json=lambda _s, _u, **_k: {
            "entities": [{"category": "person", "text": "Alice"}, {"category": "person", "text": "NotInDoc"}]
        }
    )
    redact = client.post(
        "/api/v1/redaction/detect-entities",
        headers=auth_header,
        json={"documentText": "Alice works here."},
    )
    assert redact.status_code == 200
    texts = [e["text"] for e in redact.json()["entities"]]
    assert texts == ["Alice"]

    set_llm_overrides(
        complete_json=lambda _s, _u, **_k: {
            "overview": "Tighten term.",
            "edits": [
                {
                    "label": "Term",
                    "currentLanguage": "one year",
                    "proposedLanguage": "two years",
                    "rationale": "Longer term",
                    "grounding": "verified",
                },
                {
                    "label": "Hallucinated",
                    "currentLanguage": "not in the document at all",
                    "proposedLanguage": "x",
                    "rationale": "no",
                },
            ],
            "summary": "done",
        }
    )
    edited = client.post(
        "/api/v1/drafting/edit-document",
        headers=auth_header,
        json={"documentText": "The term is one year.", "instruction": "Extend the term."},
    )
    assert edited.status_code == 200
    grounds = {e["label"]: e["grounding"] for e in edited.json()["edits"]}
    assert grounds["Term"] == "verified"
    assert grounds["Hallucinated"] == "unverified"

    stream = client.post(
        "/api/v1/drafting/edit-document/stream",
        headers=auth_header,
        json={"documentText": "The term is one year.", "instruction": "Extend the term."},
    )
    assert stream.status_code == 200
    assert "done" in stream.text

    oversized = client.post(
        "/api/v1/drafting/edit-document",
        headers=auth_header,
        json={"documentText": "x" * 200_001, "instruction": "noop"},
    )
    assert oversized.status_code == 413


def test_document_tools_require_auth(client):
    assert client.post("/api/v1/drafting/extract-text").status_code == 401

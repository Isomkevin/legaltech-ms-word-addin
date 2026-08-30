from app.services.grounding import compute_approval_gate, normalize_redline, shape_review


DOC = "The term of this Agreement is twelve months from the Effective Date."


def test_verified_when_current_language_is_literal_substring():
    r = normalize_redline(
        {"clauseName": "Term", "currentLanguage": "twelve months", "proposedLanguage": "24 months"},
        DOC,
    )
    assert r["grounding"] == "verified"
    assert r["currentLanguage"] == "twelve months"


def test_unverified_when_model_paraphrases():
    r = normalize_redline(
        {"clauseName": "Term", "currentLanguage": "a period of one year", "proposedLanguage": "24 months"},
        DOC,
    )
    assert r["grounding"] == "unverified"


def test_insertion_when_current_language_empty():
    r = normalize_redline({"clauseName": "Insurance", "currentLanguage": "", "proposedLanguage": "Party A shall..."}, DOC)
    assert r["grounding"] == "insertion"


def test_model_verified_label_is_ignored():
    r = normalize_redline(
        {
            "clauseName": "Term",
            "currentLanguage": "not in the document",
            "proposedLanguage": "x",
            "grounding": "verified",
        },
        DOC,
    )
    assert r["grounding"] == "unverified"


def test_approval_gate_required_only_for_deal_breakers():
    redlines = [
        normalize_redline({"clauseName": "A", "currentLanguage": "twelve months", "isDealBreaker": True}, DOC),
        normalize_redline({"clauseName": "B", "currentLanguage": "twelve months", "isDealBreaker": False}, DOC),
    ]
    gate = compute_approval_gate(redlines)
    assert gate["required"] is True
    assert gate["dealBreakerCount"] == 1
    assert "deal-breaker" in gate["summary"]

    clean = compute_approval_gate([redlines[1]])
    assert clean["required"] is False
    assert clean["dealBreakerCount"] == 0
    assert clean["summary"] == "No deal-breakers flagged."


def test_shape_review_never_invents_liability_or_counterparty():
    review = shape_review(
        {"summary": "ok", "overallRisk": "green", "redlines": [], "flags": []},
        DOC,
        "an-1",
        "nda",
        "recipient",
    )
    assert review["id"] == "an-1"
    assert review["liabilityExposure"] is None
    assert review["counterpartyMatch"] is None
    assert review["approvalGate"]["required"] is False

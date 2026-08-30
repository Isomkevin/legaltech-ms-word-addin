from app.models.schemas import (
    ContractReviewRequest,
    DraftListItem,
    GenerateDraftRequest,
    Me,
    QuotaSummary,
    QuotaUsage,
    RewriteRequest,
    UsageMetric,
)


def test_review_request_accepts_camel_case():
    req = ContractReviewRequest.model_validate(
        {
            "documentText": "hello",
            "contractType": "nda",
            "userSide": "recipient",
            "jurisdiction": "US",
            "markupLevel": "standard",
        }
    )
    assert req.document_text == "hello"
    assert req.contract_type == "nda"
    assert req.user_side == "recipient"


def test_me_serializes_camel_case():
    dumped = Me(
        user_id="u1",
        email="a@b.c",
        full_name="Ada",
        organization_id="org-1",
        initialized=True,
    ).model_dump(by_alias=True)
    assert dumped["userId"] == "u1"
    assert dumped["fullName"] == "Ada"
    assert dumped["organizationId"] == "org-1"
    assert dumped["initialized"] is True


def test_quota_serializes_usage_keys_the_pane_reads():
    dumped = QuotaSummary(
        tier="mvp",
        tier_name="HakiChain AI",
        usage=QuotaUsage(
            monthly_messages=UsageMetric(current=1, limit=100, percentage=1),
            monthly_legal_tool_uses=UsageMetric(current=0, limit=100, percentage=0),
            monthly_full_drafts=UsageMetric(current=0, limit=100, percentage=0),
            monthly_deep_searches=UsageMetric(current=0, limit=100, percentage=0),
        ),
    ).model_dump(by_alias=True)
    assert dumped["tierName"] == "HakiChain AI"
    usage = dumped["usage"]
    assert "monthlyMessages" in usage
    assert "monthlyLegalToolUses" in usage
    assert "monthlyFullDrafts" in usage


def test_draft_list_item_camel_case():
    dumped = DraftListItem(
        id="d1",
        title="NDA",
        category="nda",
        generation_status="completed",
        updated_at="2026-01-01T00:00:00Z",
    ).model_dump(by_alias=True)
    assert dumped["generationStatus"] == "completed"
    assert dumped["updatedAt"] == "2026-01-01T00:00:00Z"


def test_drafting_generate_reads_snake_case_field_names():
    req = GenerateDraftRequest.model_validate(
        {
            "category": "nda",
            "title": "Mutual NDA",
            "special_instructions": "Keep it short",
            "governing_law_state": "CA",
            "reference_document_ids": ["r1"],
        }
    )
    assert req.special_instructions == "Keep it short"
    assert req.governing_law_state == "CA"


def test_rewrite_request_reads_snake_case():
    req = RewriteRequest.model_validate(
        {"clause_text": "Party A shall...", "instruction": "Simplify", "mode": "simplify", "tone": "balanced"}
    )
    assert req.clause_text.startswith("Party")

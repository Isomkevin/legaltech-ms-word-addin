"""Pydantic mirrors of the Word add-in wire shapes.

Legal-tools / chat / playbooks: camelCase in and out (alias_generator + populate_by_name).
Drafting generate / clause tools: snake_case input field names, camelCase output.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        extra="allow",
    )


class SnakeModel(BaseModel):
    """Input-by-field-name (snake_case). Used for drafting generate / clause tools."""

    model_config = ConfigDict(extra="allow")


# --- Auth / quota -----------------------------------------------------------


class Me(CamelModel):
    user_id: str
    email: str | None = None
    full_name: str | None = None
    organization_id: str | None = None
    is_admin: bool = False
    initialized: bool = True


class UsageMetric(CamelModel):
    current: int
    limit: int
    percentage: float


class QuotaUsage(CamelModel):
    monthly_messages: UsageMetric | None = None
    monthly_deep_searches: UsageMetric | None = None
    monthly_legal_tool_uses: UsageMetric | None = None
    monthly_full_drafts: UsageMetric | None = None


class QuotaSummary(CamelModel):
    tier: str
    tier_name: str
    usage: QuotaUsage | None = None


# --- Contract review --------------------------------------------------------


class DealContext(CamelModel):
    governing_law: str | None = None


class ContractReviewRequest(CamelModel):
    document_text: str
    contract_type: str = ""
    user_side: str = ""
    jurisdiction: str = "US"
    deal_context: DealContext | None = None
    playbook_id: str | None = None
    review_instructions: str | None = None
    matter_id: str | None = None
    markup_level: Literal["light", "standard", "firm"] | None = "standard"
    paper_side: Literal["own", "counterparty"] | None = None


class ClassifyRequest(CamelModel):
    document_text: str


class ClassifyResponse(CamelModel):
    contract_type: str | None = None
    confidence: float = 0.0


class ReviewApprovalReason(CamelModel):
    clause_name: str | None = None
    level: str | None = None
    reason: str | None = None


class ReviewApprovalGate(CamelModel):
    required: bool
    level: Literal["manager", "partner", "gc"] | None = None
    deal_breaker_count: int = 0
    reasons: list[ReviewApprovalReason] = Field(default_factory=list)
    summary: str = ""


class RedlineSuggestion(CamelModel):
    clause_name: str
    section_reference: str | None = None
    current_language: str = ""
    proposed_language: str = ""
    rationale: str = ""
    fallback_position: str | None = None
    grounding: Literal["verified", "unverified", "insertion"] = "unverified"
    approval_level: Literal["none", "manager", "partner", "gc"] | None = None
    is_deal_breaker: bool = False
    nature: Literal["substantive", "housekeeping"] | None = None


class NegotiationPriority(CamelModel):
    tier: int
    tier_label: str
    items: list[str] = Field(default_factory=list)


class ReviewFlag(CamelModel):
    clause_name: str
    section_reference: str | None = None
    observation: str = ""


class ContractReviewResponse(CamelModel):
    id: str
    summary: str = ""
    overall_risk: str = "yellow"
    contract_type: str | None = None
    user_side: str | None = None
    redlines: list[RedlineSuggestion] = Field(default_factory=list)
    negotiation_priorities: list[NegotiationPriority] = Field(default_factory=list)
    missing_clauses: list[str] = Field(default_factory=list)
    business_impact_summary: str | None = None
    approval_gate: ReviewApprovalGate | None = None
    model_used: str | None = None
    processing_time_ms: int | None = None
    clauses: list[dict[str, Any]] | None = None
    liability_exposure: None = None
    counterparty_match: None = None
    flags: list[ReviewFlag] = Field(default_factory=list)


class ClauseFixRequest(CamelModel):
    clause_name: str
    clause_type: str = ""
    current_language: str = ""
    user_side: str | None = None
    paper_side: Literal["own", "counterparty"] | None = None
    playbook_id: str | None = None
    jurisdiction: str | None = "US"


# --- Chat -------------------------------------------------------------------


class ChatMessage(CamelModel):
    role: Literal["user", "assistant"]
    content: str


class StreamChatRequest(CamelModel):
    messages: list[ChatMessage]
    context: str | None = None
    use_rag: bool = True
    country_code: str = "US"
    client_message_id: str | None = None
    matter_id: str | None = None
    enable_matter_docs_search: bool | None = None
    enable_vaquill_db_search: bool | None = None
    enable_web_search: bool | None = None
    us_states: list[str] | None = None


# --- Clause / legal tools ---------------------------------------------------


class RewriteRequest(SnakeModel):
    clause_text: str
    instruction: str = "Rewrite for clarity and legal precision"
    jurisdiction: str = "US"
    mode: str = "rewrite"
    tone: str = "balanced"


class RewriteResult(CamelModel):
    original: str
    rewritten: str
    changes_summary: str
    provenance: dict[str, Any] | None = None


class ExplainRequest(SnakeModel):
    clause_text: str
    jurisdiction: str = "US"


class ExplainResult(CamelModel):
    explanation: str
    key_obligations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    applicable_acts: list[str] = Field(default_factory=list)


class PlainEnglishRequest(CamelModel):
    text: str


class RiskRequest(CamelModel):
    document_text: str
    risk_category: str = "contract"


class ComplianceRequest(CamelModel):
    document_text: str
    regulation_type: str
    document_category: str = "other"


class NdaTriageRequest(CamelModel):
    document_text: str
    counterparty_name: str | None = None
    business_context: str | None = None
    jurisdiction: str = "US"


class GuidelinesRequest(CamelModel):
    document_text: str
    guidelines: list[str]


class CitationStyleRequest(CamelModel):
    citations: list[str]


class ImprovePromptRequest(CamelModel):
    prompt: str


class ImprovePromptResult(CamelModel):
    original: str
    improved: str
    notes: str | None = None
    changed: bool = False


class PlaybookFitPosition(CamelModel):
    standard_position: str = ""
    fallback_ladder: list[str] = Field(default_factory=list)
    deal_breaker: str | None = None


class PlaybookFitRequest(CamelModel):
    document_text: str
    positions: dict[str, PlaybookFitPosition] = Field(default_factory=dict)


# --- Playbooks --------------------------------------------------------------


class PlaybookCreate(CamelModel):
    name: str
    contract_type: str = "custom"
    positions: dict[str, Any] = Field(default_factory=dict)


class PlaybookOut(CamelModel):
    id: str
    name: str
    description: str | None = None
    contract_type: str
    is_default: bool = False
    updated_at: str | None = None
    created_at: str | None = None
    organization_id: str | None = None
    positions: dict[str, Any] = Field(default_factory=dict)


class PlaybookList(CamelModel):
    playbooks: list[PlaybookOut]
    total: int


class LearningApply(CamelModel):
    clause_type: str
    text: str
    mode: str = "add_fallback"


# --- Drafting ---------------------------------------------------------------


class GenerateDraftRequest(SnakeModel):
    category: str
    title: str
    jurisdiction: str = "US"
    tone: str = "balanced"
    special_instructions: str | None = None
    governing_law_state: str | None = None
    reference_document_ids: list[str] | None = None


class GeneratedSection(CamelModel):
    id: str
    title: str
    content: str
    clause_type: str | None = None


class DraftResult(CamelModel):
    draft_id: str
    title: str
    category: str
    full_text: str
    sections: list[GeneratedSection] = Field(default_factory=list)
    quality_score: float | None = None
    issues: list[dict[str, Any]] | None = None
    authorities: list[dict[str, Any]] | None = None


class DraftListItem(CamelModel):
    id: str
    title: str
    category: str
    status: str = "draft"
    version: int = 1
    source: str | None = None
    updated_at: str | None = None
    generation_status: str | None = None


class DraftRow(CamelModel):
    id: str
    title: str
    category: str
    content: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    generation_status: str | None = None
    generation_progress: dict[str, Any] | None = None
    generation_error: str | None = None


class DraftReferenceOut(CamelModel):
    id: str
    file_name: str
    word_count: int


class ImportDraftRequest(SnakeModel):
    title: str
    category: str = "custom"
    content: dict[str, Any] | None = None
    matter_id: str | None = None
    redlines: list[dict[str, Any]] | None = None

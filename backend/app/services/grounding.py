"""Server-deterministic grounding and approval-gate helpers.

Never trust the model's own grounding label. A redline is verified only when
currentLanguage is a literal substring of the source document.
"""

from __future__ import annotations

from typing import Any


def _s(v: Any, fallback: str = "") -> str:
    return v if isinstance(v, str) else fallback


def normalize_redline(raw: Any, document: str) -> dict[str, Any]:
    o = raw if isinstance(raw, dict) else {}
    current = _s(o.get("currentLanguage") or o.get("current_language"))
    if not current:
        grounding = "insertion"
    elif current in document:
        grounding = "verified"
    else:
        grounding = "unverified"
    nature = o.get("nature")
    if nature not in ("substantive", "housekeeping"):
        nature = None
    is_deal = o.get("isDealBreaker") is True or o.get("is_deal_breaker") is True
    return {
        "clauseName": _s(o.get("clauseName") or o.get("clause_name"), "Clause"),
        "sectionReference": o.get("sectionReference") if isinstance(o.get("sectionReference"), str) else (
            o.get("section_reference") if isinstance(o.get("section_reference"), str) else None
        ),
        "currentLanguage": current,
        "proposedLanguage": _s(o.get("proposedLanguage") or o.get("proposed_language")),
        "rationale": _s(o.get("rationale")),
        "fallbackPosition": o.get("fallbackPosition") if isinstance(o.get("fallbackPosition"), str) else (
            o.get("fallback_position") if isinstance(o.get("fallback_position"), str) else None
        ),
        "grounding": grounding,
        "approvalLevel": None,
        "isDealBreaker": is_deal,
        "nature": nature,
    }


def compute_approval_gate(redlines: list[dict[str, Any]]) -> dict[str, Any]:
    deal_breakers = [r for r in redlines if r.get("isDealBreaker") is True]
    n = len(deal_breakers)
    return {
        "required": n > 0,
        "level": None,
        "dealBreakerCount": n,
        "reasons": [],
        "summary": (
            f"{n} deal-breaker issue(s) flagged; sign-off recommended before you send."
            if n
            else "No deal-breakers flagged."
        ),
    }


def shape_review(
    raw: dict[str, Any],
    document: str,
    analysis_id: str,
    contract_type: str | None,
    user_side: str | None,
) -> dict[str, Any]:
    redlines = [normalize_redline(r, document) for r in (raw.get("redlines") or [])]
    flags_raw = raw.get("flags") if isinstance(raw.get("flags"), list) else []
    flags: list[dict[str, Any]] = []
    for f in flags_raw:
        if not isinstance(f, dict):
            continue
        flags.append(
            {
                "clauseName": _s(f.get("clauseName") or f.get("clause_name"), "Clause"),
                "sectionReference": _s(f.get("sectionReference") or f.get("section_reference")) or None,
                "observation": _s(f.get("observation")),
            }
        )
    priorities_raw = raw.get("negotiationPriorities") or raw.get("negotiation_priorities") or []
    priorities: list[dict[str, Any]] = []
    if isinstance(priorities_raw, list):
        for p in priorities_raw:
            if not isinstance(p, dict):
                continue
            items = p.get("items") if isinstance(p.get("items"), list) else []
            priorities.append(
                {
                    "tier": p.get("tier") if isinstance(p.get("tier"), int) else 1,
                    "tierLabel": _s(p.get("tierLabel") or p.get("tier_label"), "Priority"),
                    "items": [i for i in items if isinstance(i, str)],
                }
            )
    missing = raw.get("missingClauses") or raw.get("missing_clauses") or []
    return {
        "id": analysis_id,
        "summary": _s(raw.get("summary")),
        "overallRisk": _s(raw.get("overallRisk") or raw.get("overall_risk"), "yellow"),
        "contractType": contract_type,
        "userSide": user_side,
        "redlines": redlines,
        "negotiationPriorities": priorities,
        "missingClauses": [m for m in missing if isinstance(m, str)] if isinstance(missing, list) else [],
        "businessImpactSummary": raw.get("businessImpactSummary")
        if isinstance(raw.get("businessImpactSummary"), str)
        else None,
        "approvalGate": compute_approval_gate(redlines),
        "liabilityExposure": None,
        "counterpartyMatch": None,
        "flags": flags,
    }

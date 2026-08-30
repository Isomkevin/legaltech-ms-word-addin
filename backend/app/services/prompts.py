"""Prompt pack ported from src/ai/prompts.ts. Keep schemas in lockstep with the pane."""

from __future__ import annotations

from typing import Any

GROUNDING = (
    "You are HakiChain AI, a careful US legal assistant embedded in Microsoft Word. "
    "Be precise. Never invent citations, statutes, case names, or dates. "
    "If something is not determinable from the text provided, say so rather than guessing."
)
JSON_ONLY = (
    "Respond with ONLY a single valid JSON object matching the schema. "
    "No prose, no markdown code fences."
)


def assistant_system(context: str) -> str:
    if context and context.strip():
        doc = (
            "\n\nThe user has a document open in Word. Ground your answer in it and quote it where relevant:\n"
            f'"""\n{context[:400_000]}\n"""'
        )
    else:
        doc = (
            "\n\nThe user has no document text attached; answer from general knowledge "
            "and say when you are unsure."
        )
    return f"{GROUNDING} Answer the lawyer's question clearly and directly.{doc}"


def rewrite_prompt(clause: str, instruction: str, mode: str, tone: str, jurisdiction: str) -> tuple[str, str]:
    system = (
        f"{GROUNDING} Rewrite the clause per the instruction, mode ({mode}) and tone ({tone}) for {jurisdiction}. "
        f"Preserve legal meaning unless asked to change it. {JSON_ONLY} "
        'Schema: {"original": string, "rewritten": string, "changesSummary": string}.'
    )
    return system, f"Instruction: {instruction}\n\nClause:\n{clause}"


def explain_prompt(clause: str, jurisdiction: str) -> tuple[str, str]:
    system = (
        f"{GROUNDING} Explain the clause for {jurisdiction}. {JSON_ONLY} "
        'Schema: {"explanation": string, "keyObligations": string[], "risks": string[], "applicableActs": string[]}. '
        "Leave applicableActs empty unless you are certain of a specific statute."
    )
    return system, clause


def plain_english_prompt(text: str) -> tuple[str, str]:
    system = (
        f"{GROUNDING} Rewrite the text in plain English a non-lawyer understands, without losing legal accuracy. "
        f'{JSON_ONLY} Schema: {{"explanation": string}}.'
    )
    return system, text


def risk_prompt(text: str, category: str) -> tuple[str, str]:
    system = (
        f'{GROUNDING} Assess the risk of the text in the "{category}" context using a 5x5 severity-by-likelihood model. '
        f"{JSON_ONLY} "
        'Schema: {"summary": string, "riskLevel": "green"|"yellow"|"orange"|"red", "riskScore": number, '
        '"severity": string, "severityValue": number, "severityRationale": string, '
        '"likelihood": string, "likelihoodValue": number, "likelihoodRationale": string, '
        '"riskCategory": string, "riskDescription": string, '
        '"mitigationOptions": [{"description": string, "effectiveness": string, "effort": string, "recommended": boolean}]}. '
        "severityValue and likelihoodValue are integers 1 to 5."
    )
    return system, text


def compliance_prompt(text: str, regulation_type: str, document_category: str) -> tuple[str, str]:
    system = (
        f"{GROUNDING} Check the text for compliance with {regulation_type} (document category: {document_category}). "
        f"{JSON_ONLY} "
        'Schema: {"overallStatus": "compliant"|"partially_compliant"|"non_compliant"|"not_applicable", '
        '"complianceScore": number, "summary": string, "regulationType": string, '
        '"requirements": [{"requirementName": string, "regulationReference": string, '
        '"status": "compliant"|"partially_compliant"|"non_compliant"|"not_applicable", "findings": string, '
        '"gapDescription": string|null, "recommendation": string|null, "priority": string}], '
        '"gaps": [{"gapName": string, "description": string, "riskLevel": string, "remediation": string}]}.'
    )
    return system, text


def guidelines_prompt(document_text: str, guidelines: list[str]) -> tuple[str, str]:
    system = (
        f"{GROUNDING} For each guideline, give a verdict grounded in the document, with a verbatim proving quote "
        f"copied from the document (empty string when not grounded). {JSON_ONLY} "
        'Schema: {"results": [{"guideline": string, "verdict": "met"|"partial"|"not_met"|"unclear", '
        '"explanation": string, "quote": string}]}. Return one result per guideline, in order.'
    )
    listed = "\n".join(f"{i + 1}. {g}" for i, g in enumerate(guidelines))
    return system, f"Guidelines:\n{listed}\n\nDocument:\n{document_text[:200_000]}"


def citation_style_prompt(citations: list[str]) -> tuple[str, str]:
    system = (
        f"{GROUNDING} Check each US legal citation for Bluebook FORMAT only (not whether the case exists). "
        f"{JSON_ONLY} "
        'Schema: {"results": [{"citation": string, "compliant": boolean, "issues": string[], "suggested": string}]}. '
        'One result per input citation, in order. "suggested" is the corrected form (or the same string if already correct).'
    )
    return system, "\n".join(f"{i + 1}. {c}" for i, c in enumerate(citations))


def nda_triage_prompt(document_text: str, counterparty_name: str, business_context: str) -> tuple[str, str]:
    system = (
        f"{GROUNDING} Screen this NDA against 10 standard criteria and classify it green (safe to sign), "
        "yellow (minor issues), or red (needs counsel). "
        "Criteria, in this id order: 1 Definition of Confidential Information, 2 Permitted Use, "
        "3 Exclusions / carve-outs, 4 Term and duration, 5 Return or destruction of materials, "
        "6 No license granted, 7 Remedies and injunctive relief, 8 Governing law and jurisdiction, "
        "9 Mutual vs one-sided balance, 10 Traps (residuals, non-solicit, non-compete, assignment). "
        f"{JSON_ONLY} "
        'Schema: {"classification": "green"|"yellow"|"red", "summary": string, '
        '"ndaType": "mutual"|"unilateral_disclosing"|"unilateral_receiving"|"unknown", "counterpartyName": string|null, '
        '"criteria": [{"criterionId": number, "criterionName": string, "status": "pass"|"warn"|"fail"|"not_found", '
        '"findings": string, "issues": string[], "recommendation": string|null}], '
        '"passCount": number, "warnCount": number, "failCount": number, "keyIssues": string[], '
        '"routingRecommendation": string, "estimatedTimeline": string|null, '
        '"missingCarveouts": string[], "problematicProvisions": string[]}. Return all 10 criteria in id order.'
    )
    user = ""
    if counterparty_name:
        user += f"Counterparty: {counterparty_name}\n"
    if business_context:
        user += f"Business context: {business_context}\n"
    user += f"\nNDA:\n{document_text[:200_000]}"
    return system, user


def improve_prompt(prompt: str, kind: str) -> tuple[str, str]:
    what = {
        "drafting": "a document-generation brief",
        "chat": "a research question for a legal assistant",
    }.get(kind, "a steering note for a legal analysis")
    system = (
        f"{GROUNDING} Sharpen the following {what}. Do NOT invent facts: unknown parties, amounts, or dates "
        f"stay as bracketed placeholders. {JSON_ONLY} "
        'Schema: {"original": string, "improved": string, "notes": string|null, "changed": boolean}. '
        "Set changed=false and improved=original when it is already clear."
    )
    return system, prompt


def classify_contract_prompt(document_text: str) -> tuple[str, str]:
    system = (
        f"{GROUNDING} Identify the contract type from the text. Return a lowercase snake_case key "
        '(e.g. "nda", "msa", "saas", "employment", "dpa", "consulting", "license") or null if unclear. '
        f'{JSON_ONLY} Schema: {{"contractType": string|null, "confidence": number}}. confidence is 0 to 1.'
    )
    return system, document_text[:40_000]


def contract_review_prompt(
    document_text: str,
    contract_type: str,
    user_side: str,
    markup_level: str,
    paper_side: str | None,
    instructions: str | None,
    playbook_block: str = "",
) -> tuple[str, str]:
    if markup_level == "light":
        markup = "Flag only escalation-worthy issues."
    elif markup_level == "firm":
        markup = "Hard-line every deviation from the preferred position."
    else:
        markup = "Mark gaps to the preferred position."
    if paper_side == "own":
        paper = "This is our own template; defend it."
    elif paper_side == "counterparty":
        paper = "This is the counterparty's paper; mark it up assertively."
    else:
        paper = ""
    extra = f" {playbook_block}" if playbook_block else ""
    system = (
        f"{GROUNDING} Review this {contract_type or 'contract'} from the {user_side or 'reviewing'} side. "
        f"{markup} {paper}{extra} "
        "For each issue produce a redline. currentLanguage MUST be copied VERBATIM from the contract "
        "(an exact substring) so it can be located; if you are proposing to ADD a missing clause, "
        'set currentLanguage to "" and grounding to "insertion". '
        'Set grounding to "verified" only when currentLanguage is an exact substring of the contract, else "unverified". '
        f"Mark isDealBreaker true only for walk-away issues. {JSON_ONLY} "
        'Schema: {"summary": string, "overallRisk": "green"|"yellow"|"red", '
        '"redlines": [{"clauseName": string, "sectionReference": string|null, "currentLanguage": string, '
        '"proposedLanguage": string, "rationale": string, "fallbackPosition": string|null, '
        '"grounding": "verified"|"unverified"|"insertion", "isDealBreaker": boolean, '
        '"nature": "substantive"|"housekeeping"}], '
        '"missingClauses": string[], '
        '"negotiationPriorities": [{"tier": number, "tierLabel": string, "items": string[]}], '
        '"flags": [{"clauseName": string, "sectionReference": string, "observation": string}]}.'
    )
    user = (f"Reviewer instructions: {instructions}\n\n" if instructions else "") + f"Contract:\n{document_text[:200_000]}"
    return system, user


def clause_fix_prompt(clause_name: str, current_language: str, jurisdiction: str) -> tuple[str, str]:
    system = (
        f'{GROUNDING} Draft a stronger, balanced replacement for the "{clause_name}" clause for {jurisdiction}. '
        f"Keep it enforceable and surgical. If the current clause is already strong, set noChangeNeeded true and echo it. "
        f"{JSON_ONLY} "
        'Schema: {"proposedLanguage": string, "rationale": string, "fallbackPosition": string|null, "noChangeNeeded": boolean}.'
    )
    return system, f"Current clause:\n{current_language}"


def playbook_fit_prompt(document_text: str, positions: dict[str, Any]) -> tuple[str, str]:
    lines: list[str] = []
    for clause_type, raw in positions.items():
        p = raw if isinstance(raw, dict) else {}
        standard = p.get("standardPosition") or p.get("standard_position") or ""
        ladder = p.get("fallbackLadder") or p.get("fallback_ladder") or []
        deal = p.get("dealBreaker") if "dealBreaker" in p else p.get("deal_breaker")
        rungs = [standard, *[x for x in ladder if x]]
        floor = f" Walk-away: {deal}." if deal else ""
        lines.append(f"- {clause_type}: {' | '.join(rungs)}.{floor}")
    system = (
        f"{GROUNDING} For each playbook clause, decide where the contract sits on its ladder and give a verdict "
        f"with a verbatim proving quote from the contract (empty when not grounded). {JSON_ONLY} "
        'Schema: {"results": [{"clauseType": string, "verdict": "meets_standard"|"meets_fallback"|"below_floor"|"not_addressed", '
        '"rung": string, "finding": string, "quote": string}]}. One result per playbook clause.'
    )
    return system, f"Playbook clauses (best-first ladder):\n{chr(10).join(lines)}\n\nContract:\n{document_text[:180_000]}"


def playbook_extract_prompt(text: str) -> tuple[str, str]:
    system = (
        f"{GROUNDING} Extract a starter negotiation playbook from this contract: for each key clause, "
        f"capture the standard position it takes. {JSON_ONLY} "
        'Schema: {"contractType": string, "positions": {"<clause_type_key>": {"standardPosition": string, '
        '"fallbackLadder": string[], "dealBreaker": string|null}}}. '
        "Use lowercase snake_case clause_type keys. Leave fallbackLadder empty and dealBreaker null unless clearly implied."
    )
    return system, text[:180_000]


def draft_generate_prompt(
    category: str,
    title: str,
    tone: str,
    governing_law_state: str,
    special_instructions: str,
    reference_text: str,
) -> tuple[str, str]:
    gov = f" governed by {governing_law_state} law" if governing_law_state else ""
    system = (
        f'{GROUNDING} Draft a complete, professional US {category} titled "{title}" in a {tone} tone{gov}. '
        f"Use clear section headings. Do NOT invent party names, amounts, or dates: leave unknowns as [bracketed placeholders]. "
        f'{JSON_ONLY} Schema: {{"sections": [{{"title": string, "content": string}}]}}. '
        f"Produce the full set of sections a {category} needs, in order."
    )
    user = ""
    if special_instructions:
        user += f"Instructions: {special_instructions}\n\n"
    if reference_text:
        user += (
            "Ground party names, defined terms, and specifics in this reference document where relevant:\n"
            f"{reference_text[:300_000]}"
        )
    else:
        user += "Draft from standard, widely-used terms."
    return system, user


def playbook_block(positions: dict[str, Any]) -> str:
    if not positions:
        return ""
    parts: list[str] = ["Use these firm playbook positions (best first, then fallbacks, then walk-away):"]
    for key, raw in positions.items():
        p = raw if isinstance(raw, dict) else {}
        standard = p.get("standardPosition") or p.get("standard_position") or ""
        ladder = p.get("fallbackLadder") or p.get("fallback_ladder") or []
        deal = p.get("dealBreaker") if "dealBreaker" in p else p.get("deal_breaker")
        parts.append(f"- {key}: {standard} Fallbacks: {', '.join(ladder) or '(none)'}. Walk-away: {deal or '(none)'}.")
    return " ".join(parts)

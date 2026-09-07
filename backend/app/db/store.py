"""Persistence for profiles, orgs, playbooks, drafts, analyses, prompts, clauses.

Uses Supabase (service role, bypasses RLS) when configured. Falls back to an
in-memory store only when REQUIRE_SUPABASE is false (tests / local).
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.errors import ApiError

SEED_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "id": "seed-nda",
        "name": "Mutual NDA (starter)",
        "contract_type": "nda",
        "is_default": True,
        "positions": {
            "confidentiality_term": {
                "standardPosition": "Confidentiality survives 3 years after termination.",
                "fallbackLadder": ["Up to 5 years", "Perpetual for trade secrets only"],
                "dealBreaker": "No fixed term / indefinite for all information.",
            },
            "permitted_use": {
                "standardPosition": "Use limited to evaluating the stated business purpose.",
                "fallbackLadder": ["Use for the ongoing relationship"],
                "dealBreaker": "Unrestricted use of disclosed information.",
            },
            "carve_outs": {
                "standardPosition": "Standard exclusions (public, already known, independently developed, required by law).",
                "fallbackLadder": [],
                "dealBreaker": "No exclusions at all.",
            },
        },
    },
    {
        "id": "seed-msa",
        "name": "MSA (starter)",
        "contract_type": "msa",
        "is_default": False,
        "positions": {
            "limitation_of_liability": {
                "standardPosition": "Liability capped at fees paid in the prior 12 months.",
                "fallbackLadder": ["Cap at 12 months' fees for each party", "2x fees for data-breach claims"],
                "dealBreaker": "Uncapped liability of any kind.",
            },
            "indemnification": {
                "standardPosition": "Mutual indemnities limited to third-party IP and confidentiality claims.",
                "fallbackLadder": ["Add third-party bodily-injury / property-damage claims"],
                "dealBreaker": "One-sided indemnity running only against us.",
            },
            "termination": {
                "standardPosition": "Either party may terminate for material breach uncured after 30 days.",
                "fallbackLadder": ["Termination for convenience on 60 days' notice"],
                "dealBreaker": "No right to terminate for the counterparty's breach.",
            },
        },
    },
    {
        "id": "seed-saas",
        "name": "SaaS subscription (starter)",
        "contract_type": "saas",
        "is_default": False,
        "positions": {
            "data_security": {
                "standardPosition": "Provider maintains SOC 2 Type II controls and notifies of a breach within 72 hours.",
                "fallbackLadder": ["Breach notice within 5 business days"],
                "dealBreaker": "No security commitments or breach-notice obligation.",
            },
            "service_levels": {
                "standardPosition": "99.9% monthly uptime with service credits as the remedy.",
                "fallbackLadder": ["99.5% uptime", "Credits only on repeated misses"],
                "dealBreaker": "No uptime commitment at all.",
            },
            "price_increases": {
                "standardPosition": "Renewal increases capped at 5% per year with 60 days' notice.",
                "fallbackLadder": ["Cap at 7%", "CPI-linked increase"],
                "dealBreaker": "Uncapped renewal price increases.",
            },
        },
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class Store(Protocol):
    async def upsert_profile(self, user_id: str, email: str | None, full_name: str | None) -> dict[str, Any]: ...
    async def default_membership(self, user_id: str) -> tuple[str | None, str | None]: ...
    async def resolve_membership(
        self, user_id: str, requested_org_id: str | None
    ) -> tuple[str | None, str | None]: ...
    async def ensure_personal_org(
        self, user_id: str, full_name: str | None, email: str | None
    ) -> str: ...
    async def list_playbooks(self, org_id: str) -> list[dict[str, Any]]: ...
    async def create_playbook(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]: ...
    async def get_playbook(self, org_id: str, playbook_id: str) -> dict[str, Any] | None: ...
    async def update_playbook(self, org_id: str, playbook_id: str, patch: dict[str, Any]) -> dict[str, Any]: ...
    async def save_analysis(self, org_id: str, user_id: str, analysis_id: str, result: dict[str, Any] | None) -> None: ...
    async def get_analysis(self, org_id: str, analysis_id: str) -> dict[str, Any] | None: ...
    async def create_draft(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]: ...
    async def get_draft(self, org_id: str, draft_id: str) -> dict[str, Any] | None: ...
    async def update_draft(self, org_id: str, draft_id: str, patch: dict[str, Any]) -> dict[str, Any]: ...
    async def list_drafts(self, org_id: str, limit: int, offset: int) -> list[dict[str, Any]]: ...
    async def save_reference(
        self, org_id: str, user_id: str, file_name: str, text: str, word_count: int
    ) -> dict[str, Any]: ...
    async def get_references(self, org_id: str, ids: list[str]) -> list[dict[str, Any]]: ...
    async def list_prompts(self, org_id: str, user_id: str) -> list[dict[str, Any]]: ...
    async def create_prompt(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]: ...
    async def get_prompt(self, org_id: str, prompt_id: str) -> dict[str, Any] | None: ...
    async def update_prompt(self, org_id: str, prompt_id: str, patch: dict[str, Any]) -> dict[str, Any]: ...
    async def delete_prompt(self, org_id: str, prompt_id: str) -> None: ...
    async def list_clauses(self, org_id: str, filters: dict[str, Any]) -> list[dict[str, Any]]: ...
    async def create_clause(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]: ...
    async def delete_clause(self, org_id: str, clause_id: str) -> None: ...
    async def ping(self) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.profiles: dict[str, dict[str, Any]] = {}
        self.orgs: dict[str, dict[str, Any]] = {}
        self.members: list[dict[str, Any]] = []
        self.playbooks: dict[str, dict[str, Any]] = {}
        self.analyses: dict[str, dict[str, Any]] = {}
        self.drafts: dict[str, dict[str, Any]] = {}
        self.references: dict[str, dict[str, Any]] = {}
        self.prompts: dict[str, dict[str, Any]] = {}
        self.clauses: dict[str, dict[str, Any]] = {}
        self.seeded_orgs: set[str] = set()

    async def upsert_profile(self, user_id: str, email: str | None, full_name: str | None) -> dict[str, Any]:
        with self._lock:
            existing = self.profiles.get(user_id, {})
            row = {
                "user_id": user_id,
                "email": email if email is not None else existing.get("email"),
                "full_name": full_name if full_name is not None else existing.get("full_name"),
                "initialized": True,
                "updated_at": _now(),
                "created_at": existing.get("created_at") or _now(),
            }
            self.profiles[user_id] = row
            return dict(row)

    def _memberships(self, user_id: str) -> list[dict[str, Any]]:
        return [m for m in self.members if m["user_id"] == user_id and m["status"] == "active"]

    async def default_membership(self, user_id: str) -> tuple[str | None, str | None]:
        with self._lock:
            rows = self._memberships(user_id)
        if not rows:
            return None, None
        return rows[0]["organization_id"], rows[0]["role"]

    async def resolve_membership(
        self, user_id: str, requested_org_id: str | None
    ) -> tuple[str | None, str | None]:
        with self._lock:
            rows = self._memberships(user_id)
        if requested_org_id:
            match = next((m for m in rows if m["organization_id"] == requested_org_id), None)
            if not match:
                raise ApiError(401, "No organization membership.", "unauthorized")
            return match["organization_id"], match["role"]
        if not rows:
            return None, None
        return rows[0]["organization_id"], rows[0]["role"]

    async def ensure_personal_org(self, user_id: str, full_name: str | None, email: str | None) -> str:
        existing_id, _ = await self.default_membership(user_id)
        if existing_id:
            return existing_id
        label = (full_name or email or "Personal").split("@")[0]
        org_id = new_id()
        ts = _now()
        with self._lock:
            self.orgs[org_id] = {"id": org_id, "name": f"{label}'s workspace", "created_at": ts}
            self.members.append(
                {
                    "id": new_id(),
                    "organization_id": org_id,
                    "user_id": user_id,
                    "role": "owner",
                    "status": "active",
                    "created_at": ts,
                }
            )
        return org_id

    async def list_playbooks(self, org_id: str) -> list[dict[str, Any]]:
        with self._lock:
            if org_id not in self.seeded_orgs:
                self._seed(org_id)
            rows = [dict(p) for p in self.playbooks.values() if p["organization_id"] == org_id]
        rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return rows

    def _seed(self, org_id: str) -> None:
        ts = _now()
        for seed in SEED_PLAYBOOKS:
            pid = f"{org_id}:{seed['id']}"
            self.playbooks[pid] = {
                "id": pid,
                "organization_id": org_id,
                "user_id": None,
                "name": seed["name"],
                "contract_type": seed["contract_type"],
                "is_default": seed["is_default"],
                "positions": seed["positions"],
                "created_at": ts,
                "updated_at": ts,
            }
        self.seeded_orgs.add(org_id)

    async def create_playbook(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]:
        ts = _now()
        pid = new_id()
        stored = {
            "id": pid,
            "organization_id": org_id,
            "user_id": user_id,
            "name": row.get("name") or "Playbook",
            "contract_type": row.get("contract_type") or "custom",
            "is_default": False,
            "positions": row.get("positions") or {},
            "created_at": ts,
            "updated_at": ts,
        }
        with self._lock:
            self.playbooks[pid] = stored
        return dict(stored)

    async def get_playbook(self, org_id: str, playbook_id: str) -> dict[str, Any] | None:
        with self._lock:
            if org_id not in self.seeded_orgs:
                self._seed(org_id)
            row = self.playbooks.get(playbook_id)
            if row and row["organization_id"] == org_id:
                return dict(row)
        return None

    async def update_playbook(self, org_id: str, playbook_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            row = self.playbooks.get(playbook_id)
            if not row or row["organization_id"] != org_id:
                raise ApiError(404, "Playbook not found.", "not_found")
            row = {**row, **patch, "updated_at": _now()}
            self.playbooks[playbook_id] = row
            return dict(row)

    async def save_analysis(
        self, org_id: str, user_id: str, analysis_id: str, result: dict[str, Any] | None
    ) -> None:
        with self._lock:
            self.analyses[analysis_id] = {
                "id": analysis_id,
                "organization_id": org_id,
                "user_id": user_id,
                "result": result,
                "created_at": _now(),
            }

    async def get_analysis(self, org_id: str, analysis_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.analyses.get(analysis_id)
            if row and row["organization_id"] == org_id:
                return dict(row)
        return None

    async def create_draft(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]:
        did = row.get("id") or new_id()
        ts = _now()
        stored = {
            "id": did,
            "organization_id": org_id,
            "user_id": user_id,
            "title": row.get("title") or "Untitled draft",
            "category": row.get("category") or "custom",
            "content": row.get("content"),
            "metadata": row.get("metadata") or {},
            "status": row.get("status") or "draft",
            "version": row.get("version") or 1,
            "source": row.get("source") or "generated",
            "generation_status": row.get("generation_status"),
            "generation_progress": row.get("generation_progress"),
            "generation_error": row.get("generation_error"),
            "created_at": ts,
            "updated_at": ts,
        }
        with self._lock:
            self.drafts[did] = stored
        return dict(stored)

    async def get_draft(self, org_id: str, draft_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.drafts.get(draft_id)
            if row and row["organization_id"] == org_id:
                return dict(row)
        return None

    async def update_draft(self, org_id: str, draft_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            row = self.drafts.get(draft_id)
            if not row or row["organization_id"] != org_id:
                raise ApiError(404, "Draft not found.", "not_found")
            row = {**row, **patch, "updated_at": _now()}
            self.drafts[draft_id] = row
            return dict(row)

    async def list_drafts(self, org_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(d) for d in self.drafts.values() if d["organization_id"] == org_id]
        rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return rows[offset : offset + limit]

    async def save_reference(
        self, org_id: str, user_id: str, file_name: str, text: str, word_count: int
    ) -> dict[str, Any]:
        rid = new_id()
        row = {
            "id": rid,
            "organization_id": org_id,
            "user_id": user_id,
            "file_name": file_name,
            "text": text,
            "word_count": word_count,
            "created_at": _now(),
        }
        with self._lock:
            self.references[rid] = row
        return dict(row)

    async def get_references(self, org_id: str, ids: list[str]) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(self.references[i]) for i in ids if i in self.references and self.references[i]["organization_id"] == org_id]

    async def list_prompts(self, org_id: str, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(p)
                for p in self.prompts.values()
                if p["organization_id"] == org_id
                and (p.get("user_id") == user_id or p.get("scope") == "org")
            ]
        rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return rows

    async def create_prompt(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]:
        ts = _now()
        stored = {
            "id": new_id(),
            "user_id": user_id,
            "organization_id": org_id,
            "title": row.get("title") or "Untitled",
            "body": row.get("body") or "",
            "scope": row.get("scope") if row.get("scope") in ("private", "org") else "private",
            "created_at": ts,
            "updated_at": ts,
        }
        with self._lock:
            self.prompts[stored["id"]] = stored
        return dict(stored)

    async def get_prompt(self, org_id: str, prompt_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.prompts.get(prompt_id)
            if row and row["organization_id"] == org_id:
                return dict(row)
        return None

    async def update_prompt(self, org_id: str, prompt_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            row = self.prompts.get(prompt_id)
            if not row or row["organization_id"] != org_id:
                raise ApiError(404, "Prompt not found.", "not_found")
            row = {**row, **patch, "updated_at": _now()}
            self.prompts[prompt_id] = row
            return dict(row)

    async def delete_prompt(self, org_id: str, prompt_id: str) -> None:
        with self._lock:
            row = self.prompts.get(prompt_id)
            if not row or row["organization_id"] != org_id:
                raise ApiError(404, "Prompt not found.", "not_found")
            del self.prompts[prompt_id]

    async def list_clauses(self, org_id: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(c) for c in self.clauses.values() if c["organization_id"] == org_id]
        if filters.get("clause_type"):
            rows = [r for r in rows if r.get("clause_type") == filters["clause_type"]]
        if filters.get("jurisdiction"):
            rows = [r for r in rows if r.get("jurisdiction") == filters["jurisdiction"]]
        if filters.get("tone"):
            rows = [r for r in rows if r.get("tone") == filters["tone"]]
        if filters.get("source"):
            rows = [r for r in rows if r.get("source") == filters["source"]]
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        limit = int(filters.get("limit") or 100)
        offset = int(filters.get("offset") or 0)
        return rows[offset : offset + limit]

    async def create_clause(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]:
        ts = _now()
        stored = {
            "id": new_id(),
            "organization_id": org_id,
            "user_id": user_id,
            "name": row.get("name") or "Clause",
            "clause_type": row.get("clause_type") or row.get("clauseType") or "custom",
            "content": row.get("content") or "",
            "jurisdiction": row.get("jurisdiction") or "US",
            "tone": row.get("tone") or "balanced",
            "applicable_acts": row.get("applicable_acts") or [],
            "tags": row.get("tags") or [],
            "applicable_categories": row.get("applicable_categories"),
            "source": row.get("source") or "user",
            "is_system": bool(row.get("is_system")),
            "created_at": ts,
        }
        with self._lock:
            self.clauses[stored["id"]] = stored
        return dict(stored)

    async def delete_clause(self, org_id: str, clause_id: str) -> None:
        with self._lock:
            row = self.clauses.get(clause_id)
            if not row or row["organization_id"] != org_id:
                raise ApiError(404, "Clause not found.", "not_found")
            if row.get("is_system"):
                raise ApiError(400, "System clauses cannot be deleted.", "invalid")
            del self.clauses[clause_id]

    async def ping(self) -> None:
        return None


class SupabaseStore:
    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, key)

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    async def upsert_profile(self, user_id: str, email: str | None, full_name: str | None) -> dict[str, Any]:
        payload = {
            "user_id": user_id,
            "email": email,
            "full_name": full_name,
            "initialized": True,
            "updated_at": _now(),
        }
        res = await self._run(lambda: self._client.table("profiles").upsert(payload, on_conflict="user_id").execute())
        rows = res.data or []
        return rows[0] if rows else payload

    async def default_membership(self, user_id: str) -> tuple[str | None, str | None]:
        res = await self._run(
            lambda: self._client.table("organization_members")
            .select("organization_id, role")
            .eq("user_id", user_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None, None
        return rows[0]["organization_id"], rows[0].get("role")

    async def resolve_membership(
        self, user_id: str, requested_org_id: str | None
    ) -> tuple[str | None, str | None]:
        def work():
            q = (
                self._client.table("organization_members")
                .select("organization_id, role")
                .eq("user_id", user_id)
                .eq("status", "active")
            )
            if requested_org_id:
                q = q.eq("organization_id", requested_org_id)
            return q.limit(1).execute()

        res = await self._run(work)
        rows = res.data or []
        if requested_org_id and not rows:
            raise ApiError(401, "No organization membership.", "unauthorized")
        if not rows:
            return None, None
        return rows[0]["organization_id"], rows[0].get("role")

    async def ensure_personal_org(self, user_id: str, full_name: str | None, email: str | None) -> str:
        existing, _ = await self.default_membership(user_id)
        if existing:
            return existing
        label = (full_name or email or "Personal").split("@")[0]
        org_id = new_id()
        ts = _now()

        def work():
            self._client.table("organizations").insert(
                {"id": org_id, "name": f"{label}'s workspace", "created_at": ts}
            ).execute()
            self._client.table("organization_members").insert(
                {
                    "id": new_id(),
                    "organization_id": org_id,
                    "user_id": user_id,
                    "role": "owner",
                    "status": "active",
                    "created_at": ts,
                }
            ).execute()

        await self._run(work)
        return org_id

    async def list_playbooks(self, org_id: str) -> list[dict[str, Any]]:
        def fetch():
            return (
                self._client.table("playbooks")
                .select("*")
                .eq("organization_id", org_id)
                .order("updated_at", desc=True)
                .execute()
            )

        res = await self._run(fetch)
        rows = list(res.data or [])
        if not rows:
            await self._seed(org_id)
            res = await self._run(fetch)
            rows = list(res.data or [])
        return rows

    async def _seed(self, org_id: str) -> None:
        ts = _now()
        payload = [
            {
                "id": f"{org_id}:{seed['id']}",
                "organization_id": org_id,
                "name": seed["name"],
                "contract_type": seed["contract_type"],
                "is_default": seed["is_default"],
                "positions": seed["positions"],
                "created_at": ts,
                "updated_at": ts,
            }
            for seed in SEED_PLAYBOOKS
        ]
        await self._run(lambda: self._client.table("playbooks").upsert(payload, on_conflict="id").execute())

    async def create_playbook(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]:
        ts = _now()
        payload = {
            "id": new_id(),
            "organization_id": org_id,
            "user_id": user_id,
            "name": row.get("name") or "Playbook",
            "contract_type": row.get("contract_type") or "custom",
            "is_default": False,
            "positions": row.get("positions") or {},
            "created_at": ts,
            "updated_at": ts,
        }
        res = await self._run(lambda: self._client.table("playbooks").insert(payload).execute())
        return (res.data or [payload])[0]

    async def get_playbook(self, org_id: str, playbook_id: str) -> dict[str, Any] | None:
        res = await self._run(
            lambda: self._client.table("playbooks")
            .select("*")
            .eq("id", playbook_id)
            .eq("organization_id", org_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    async def update_playbook(self, org_id: str, playbook_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = await self.get_playbook(org_id, playbook_id)
        if not existing:
            raise ApiError(404, "Playbook not found.", "not_found")
        payload = {**patch, "updated_at": _now()}
        res = await self._run(
            lambda: self._client.table("playbooks")
            .update(payload)
            .eq("id", playbook_id)
            .eq("organization_id", org_id)
            .execute()
        )
        return (res.data or [{**existing, **payload}])[0]

    async def save_analysis(
        self, org_id: str, user_id: str, analysis_id: str, result: dict[str, Any] | None
    ) -> None:
        await self._run(
            lambda: self._client.table("analyses")
            .upsert(
                {
                    "id": analysis_id,
                    "organization_id": org_id,
                    "user_id": user_id,
                    "result": result,
                    "created_at": _now(),
                },
                on_conflict="id",
            )
            .execute()
        )

    async def get_analysis(self, org_id: str, analysis_id: str) -> dict[str, Any] | None:
        res = await self._run(
            lambda: self._client.table("analyses")
            .select("*")
            .eq("id", analysis_id)
            .eq("organization_id", org_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    async def create_draft(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]:
        ts = _now()
        payload = {
            "id": row.get("id") or new_id(),
            "organization_id": org_id,
            "user_id": user_id,
            "title": row.get("title") or "Untitled draft",
            "category": row.get("category") or "custom",
            "content": row.get("content"),
            "metadata": row.get("metadata") or {},
            "status": row.get("status") or "draft",
            "version": row.get("version") or 1,
            "source": row.get("source") or "generated",
            "generation_status": row.get("generation_status"),
            "generation_progress": row.get("generation_progress"),
            "generation_error": row.get("generation_error"),
            "created_at": ts,
            "updated_at": ts,
        }
        res = await self._run(lambda: self._client.table("drafts").insert(payload).execute())
        return (res.data or [payload])[0]

    async def get_draft(self, org_id: str, draft_id: str) -> dict[str, Any] | None:
        res = await self._run(
            lambda: self._client.table("drafts")
            .select("*")
            .eq("id", draft_id)
            .eq("organization_id", org_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    async def update_draft(self, org_id: str, draft_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = await self.get_draft(org_id, draft_id)
        if not existing:
            raise ApiError(404, "Draft not found.", "not_found")
        payload = {**patch, "updated_at": _now()}
        res = await self._run(
            lambda: self._client.table("drafts")
            .update(payload)
            .eq("id", draft_id)
            .eq("organization_id", org_id)
            .execute()
        )
        return (res.data or [{**existing, **payload}])[0]

    async def list_drafts(self, org_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
        res = await self._run(
            lambda: self._client.table("drafts")
            .select("*")
            .eq("organization_id", org_id)
            .order("updated_at", desc=True)
            .range(offset, offset + max(limit, 1) - 1)
            .execute()
        )
        return list(res.data or [])

    async def save_reference(
        self, org_id: str, user_id: str, file_name: str, text: str, word_count: int
    ) -> dict[str, Any]:
        payload = {
            "id": new_id(),
            "organization_id": org_id,
            "user_id": user_id,
            "file_name": file_name,
            "text": text,
            "word_count": word_count,
            "created_at": _now(),
        }
        res = await self._run(lambda: self._client.table("draft_references").insert(payload).execute())
        return (res.data or [payload])[0]

    async def get_references(self, org_id: str, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        res = await self._run(
            lambda: self._client.table("draft_references")
            .select("*")
            .eq("organization_id", org_id)
            .in_("id", ids)
            .execute()
        )
        return list(res.data or [])

    async def list_prompts(self, org_id: str, user_id: str) -> list[dict[str, Any]]:
        res = await self._run(
            lambda: self._client.table("prompts")
            .select("*")
            .eq("organization_id", org_id)
            .order("updated_at", desc=True)
            .execute()
        )
        rows = list(res.data or [])
        return [r for r in rows if r.get("user_id") == user_id or r.get("scope") == "org"]

    async def create_prompt(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]:
        ts = _now()
        payload = {
            "id": new_id(),
            "user_id": user_id,
            "organization_id": org_id,
            "title": row.get("title") or "Untitled",
            "body": row.get("body") or "",
            "scope": row.get("scope") if row.get("scope") in ("private", "org") else "private",
            "created_at": ts,
            "updated_at": ts,
        }
        res = await self._run(lambda: self._client.table("prompts").insert(payload).execute())
        return (res.data or [payload])[0]

    async def get_prompt(self, org_id: str, prompt_id: str) -> dict[str, Any] | None:
        res = await self._run(
            lambda: self._client.table("prompts")
            .select("*")
            .eq("id", prompt_id)
            .eq("organization_id", org_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    async def update_prompt(self, org_id: str, prompt_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = await self.get_prompt(org_id, prompt_id)
        if not existing:
            raise ApiError(404, "Prompt not found.", "not_found")
        payload = {**patch, "updated_at": _now()}
        res = await self._run(
            lambda: self._client.table("prompts")
            .update(payload)
            .eq("id", prompt_id)
            .eq("organization_id", org_id)
            .execute()
        )
        return (res.data or [{**existing, **payload}])[0]

    async def delete_prompt(self, org_id: str, prompt_id: str) -> None:
        existing = await self.get_prompt(org_id, prompt_id)
        if not existing:
            raise ApiError(404, "Prompt not found.", "not_found")
        await self._run(
            lambda: self._client.table("prompts")
            .delete()
            .eq("id", prompt_id)
            .eq("organization_id", org_id)
            .execute()
        )

    async def list_clauses(self, org_id: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        def work():
            q = self._client.table("clauses").select("*").eq("organization_id", org_id)
            if filters.get("clause_type"):
                q = q.eq("clause_type", filters["clause_type"])
            if filters.get("jurisdiction"):
                q = q.eq("jurisdiction", filters["jurisdiction"])
            if filters.get("tone"):
                q = q.eq("tone", filters["tone"])
            if filters.get("source"):
                q = q.eq("source", filters["source"])
            limit = int(filters.get("limit") or 100)
            offset = int(filters.get("offset") or 0)
            return q.order("created_at", desc=True).range(offset, offset + max(limit, 1) - 1).execute()

        res = await self._run(work)
        return list(res.data or [])

    async def create_clause(self, org_id: str, user_id: str, row: dict[str, Any]) -> dict[str, Any]:
        ts = _now()
        payload = {
            "id": new_id(),
            "organization_id": org_id,
            "user_id": user_id,
            "name": row.get("name") or "Clause",
            "clause_type": row.get("clause_type") or row.get("clauseType") or "custom",
            "content": row.get("content") or "",
            "jurisdiction": row.get("jurisdiction") or "US",
            "tone": row.get("tone") or "balanced",
            "applicable_acts": row.get("applicable_acts") or [],
            "tags": row.get("tags") or [],
            "applicable_categories": row.get("applicable_categories"),
            "source": row.get("source") or "user",
            "is_system": bool(row.get("is_system")),
            "created_at": ts,
        }
        res = await self._run(lambda: self._client.table("clauses").insert(payload).execute())
        return (res.data or [payload])[0]

    async def delete_clause(self, org_id: str, clause_id: str) -> None:
        res = await self._run(
            lambda: self._client.table("clauses")
            .select("*")
            .eq("id", clause_id)
            .eq("organization_id", org_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise ApiError(404, "Clause not found.", "not_found")
        if rows[0].get("is_system"):
            raise ApiError(400, "System clauses cannot be deleted.", "invalid")
        await self._run(
            lambda: self._client.table("clauses")
            .delete()
            .eq("id", clause_id)
            .eq("organization_id", org_id)
            .execute()
        )

    async def ping(self) -> None:
        await self._run(lambda: self._client.table("organizations").select("id").limit(1).execute())


QUEUE_TTL = timedelta(minutes=15)


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def expire_stale_generation(store: Store, org_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """Mark in-process queued drafts as failed if they stayed running past the TTL."""
    if row.get("generation_status") != "running":
        return row
    ts = parse_ts(row.get("updated_at"))
    if ts is None or datetime.now(timezone.utc) - ts < QUEUE_TTL:
        return row
    return await store.update_draft(
        org_id,
        row["id"],
        {
            "generation_status": "failed",
            "generation_error": "Draft generation timed out. Try Generate again.",
        },
    )


def require_supabase_or_raise() -> None:
    settings = get_settings()
    if settings.require_supabase and not settings.has_supabase:
        raise RuntimeError(
            "REQUIRE_SUPABASE is set but SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing."
        )


_store: Store | None = None


def reset_store(store: Store | None = None) -> Store:
    global _store
    _store = store if store is not None else MemoryStore()
    return _store


def get_store() -> Store:
    global _store
    if _store is None:
        require_supabase_or_raise()
        settings = get_settings()
        if settings.has_supabase:
            _store = SupabaseStore(settings.supabase_url, settings.supabase_service_role_key)
        else:
            _store = MemoryStore()
    return _store

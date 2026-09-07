# AGENTS.md

Canonical brief for any coding agent landing on this repository (Cursor, Claude Code, Codex, Copilot, Amp, Jules, and others). Read this before changing code. File-scoped Cursor rules live in [`.cursor/rules/`](.cursor/rules/). Product docs for humans: [README.md](README.md). Deploy: [DEPLOY.md](DEPLOY.md). Backend: [backend/README.md](backend/README.md).

`CLAUDE.md` is a short operational digest that must stay consistent with this file. If they disagree, this file wins, then fix `CLAUDE.md`.

---

## 30-second orientation

This is **HakiChain for Microsoft Word**: a task-pane add-in (Vite + React 18 + TypeScript + Office.js, WordApi 1.6 floor).

It has **two editions** from one codebase:

| Edition | How it runs | Legal intelligence |
| --- | --- | --- |
| **Hosted** (`npm run dev` / `npm run build`) | Supabase PKCE login, JWT bearer + SSE to this repo's FastAPI app | Backend + corpus |
| **Community / BYOK** (`npm run dev:community` / `npm run build:community`) | User's own key (or local Ollama). No account | `src/community/` + `src/ai/` talk to the user's provider. IndexedDB for libraries |

The open Word document is the subject. There is no upload-first workflow. The pane reads the document through Office.js, calls an API (hosted or local shim), and writes results back as native tracked changes, comments, content controls, and custom XML.

This repo **includes** the hosted API in [`backend/`](backend/). It is a Word-add-in MVP, not a copy of every HakiChain web-app surface. Statute corpus, billed quotas, OCR, and compare still return empty or not-found shapes in places. See [backend/README.md](backend/README.md).

---

## What this repo is not

- Not a standalone LLM toy. The hosted build will not run with only a provider API key in the pane (that is the community edition).
- Not the HakiChain web app (`app.hakichain.com`). Case-law research, playbook/template/draft **libraries**, and account admin live on the web app and are reached by deep-link, not extra Word tabs.
- Not a place to invent a second Office.js stack. All `Word.run` goes through `src/office/`.

---

## Commands

Requires Node 20+ and (for sideload) a Microsoft 365 account plus Word desktop or web.

```bash
npm install
cp .env.example .env                 # hosted: VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
npx office-addin-dev-certs install   # trusted HTTPS for localhost (once)
npm run dev                          # hosted pane at https://localhost:3000 -> API http://localhost:8000
npm run dev:community                # BYOK pane, no backend
npm run sideload                     # manifest.dev.xml into Word desktop
npm run sideload:stop
npm run type-check                   # tsc --noEmit
npm run test                         # vitest (src/**/*.test.ts)
npm run build                        # hosted dist/
npm run build:community              # community dist/
npm run lint
npm run validate:manifest            # production manifest.xml
```

Hosted API (separate process):

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# then sql/001_init.sql and sql/002_prompts_clauses.sql in Supabase
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
cd backend && pytest -q              # in-memory store; no live LLM
```

Change gate for a contribution: green `npm run type-check` and `npm run build`. If you touch `backend/`, also `pytest -q`.

Do not commit, push, or amend unless the human explicitly asks in that turn.

---

## Architecture

```text
Word (desktop / Mac / web)
  task pane (word.hakichain.com or https://localhost:3000)
        |  Office.js  ->  the open document
        |
        |  hosted: Supabase JWT (Bearer) + SSE  ->  backend/ at api.hakichain.com (dev: :8000)
        |  community: src/community localRouter / localStream  ->  user's provider + IndexedDB
```

- **Task pane** is a static SPA. Three HTML entries, same origin: `index.html` (pane), `auth.html` (Office Dialog PKCE), `dictation.html` (mic; the pane iframe cannot get the microphone). `preview.html` is a local UI harness only (`npm run dev`), excluded from production builds.
- **Path alias:** `@/` -> `src/`.
- **Config:** [`src/config.ts`](src/config.ts). `apiBase` / `appBase` are fixed by `import.meta.env.PROD` (dev API is `http://localhost:8000`, prod is `https://api.hakichain.com`). Supabase URL + **anon** key are Vite env / Docker build args. The add-in origin is `window.location.origin`. The client bundle holds **no secrets**. `service_role` must never appear in the pane, Vite env, or Docker **build args**.
- **Edition flag:** `VITE_EDITION=community` at build time, or runtime BYOK via `src/community/edition.ts` (`hakichain.byokMode` in localStorage, plus an in-memory fallback when storage is blocked). When community, `src/api/http.ts` and `src/api/sse.ts` lazy-import the local shim so feature modules stay edition-agnostic.

The only CORS requirement for the hosted pane: exact origins `https://word.hakichain.com` and `https://localhost:3000` (credentials on). Allowed request headers already include `Authorization`, `Content-Type`, `X-Organization-ID`, `X-Timezone`. Never send `X-Frame-Options: DENY` (Office web hosts frame the pane).

---

## App shell

[`src/App.tsx`](src/App.tsx) + [`src/app/nav.tsx`](src/app/nav.tsx).

Four primary tabs (`AppTab`): **assistant** (default landing), **review**, **draft**, **tools**.

Review sub-nav (`ReviewSub`): **redlines**, **changes**, **compare**, **citations**, **playbooks**.

Tools launcher (`ToolKey`): `cleancopy`, `terms`, `xref`, `sendready`, `redact`, `properFormat`, `termnav`, `cockpit`, `figures`.

### Intent bus (cross-feature spine)

A lawyer's task crosses surfaces. Any view calls `navigate(tab, intent)` with a typed `AppIntent`. The target reads the intent on mount and **must** `clearIntent()` once applied so it fires exactly once. When adding a handoff, extend `AppIntent`. Do not thread ad-hoc props across tabs.

`orgVersion` (bumped on active-org change) is the React `key` on data views so matters / drafts / playbooks / clients remount and refetch.

Hosted first-run: a valid Supabase session is not enough. `GET /api/v1/auth/me` with `initialized === false` signs the user out and sends them to web signup. Fail **open** on a transient `/auth/me` error (only an explicit `initialized === false` blocks). Community skips this: [`KeyWizard`](src/features/onboarding/KeyWizard.tsx).

---

## Directory map

| Path | Purpose |
| --- | --- |
| `src/app/` | Shell nav + `AppIntent` bus |
| `src/office/` | **Only** place `Word.run` lives. Redline apply, search, comments, content controls, custom XML, export, selection, tracked-change serialize |
| `src/api/` | Bearer `fetch`, SSE parser, one module per backend surface. Feature UI talks to these, not to `fetch` |
| `src/auth/` | Office Dialog + Supabase PKCE, in-memory access token, refresh rotation |
| `src/community/` | BYOK request/stream shim, IndexedDB store, CourtListener, edition + gating |
| `src/ai/` | Provider registry (OpenAI-compatible, Anthropic, Gemini, Groq, Azure, Ollama), key store, shared prompts |
| `src/features/` | One folder per surface (assistant, review, draft, toolshub, compare, authority, playbook, ...) |
| `src/ui/` | Shared primitives, icons, tokens. White theme only. Reuse before inventing |
| `src/lib/` | Org, prefs, review snapshot XML, severity, hash, sections, clipboard |
| `src/tour/` | First-run and per-surface walkthroughs |
| `src/config.ts` | Runtime config. No secrets |
| `backend/` | FastAPI hosted API (`/api/v1/...`) |
| `manifest.xml` | Production hosted |
| `manifest.dev.xml` | Sideload hosted against localhost:3000 |
| `manifest.localhost.xml` | Sideload community against localhost:3000 |
| `manifest.community.xml` | Self-hosted community (placeholder domain + GUID) |
| `deploy/nginx.conf` | Hardened CSP / headers for the hosted pane image |

Leftover feature folders (`src/features/research`, fill, transplant, governance, ...) may still exist for specific flows or deep-links. New primary navigation goes through the four tabs + intent bus, not a new top-level tab, unless the product owner asks for one.

---

## Hard rules (do not violate)

1. **Do not add `Word.run` outside `src/office/`.** New document I/O is a helper there, called from features. Use `runWord` / `serializeTrackChanges` from `src/office/run.ts`.
2. **Reuse `src/ui/` and `src/office/`** before writing a second primitive or a second apply path.
3. **Never write tokens, API keys, or PII into `Office.Settings`.** That object serializes into the `.docx` and travels with the file. Access tokens stay in memory. Refresh token, org id, prefs, and BYOK keys use add-in-origin `localStorage` (sandboxed, does not travel with the file), always try/catch because storage can throw. Review metadata that must survive save/close/reopen goes in custom XML (`src/office/reviewState.ts` + `src/lib/reviewState.ts`). Clause anchors go in tagged content controls.
4. **Never put `SUPABASE_SERVICE_ROLE_KEY` in the pane, `.env` (root), Vite define, or Docker pane build args.** It belongs only in `backend/.env` / the API container.
5. **Never recompute server-deterministic review governance in the pane.** Render `approvalGate`, `liabilityExposure`, and `counterpartyMatch` as the backend sent them.
6. **Read the document with revision-resolved text.** `readDocumentText()` uses `body.getReviewedText(current)`, not `body.text`. `body.text` smears pending deletions and insertions together and poisons every model quote and anchor. Same rule for selection reads.
7. **Serialize change-tracking mode flips** via `serializeTrackChanges`. Overlapping save/force/restore can leave tracking OFF.
8. **Community features stay edition-agnostic at the UI/API-module layer.** Add the path to `localRouter` / `localStream` / `localForm`, or throw `REQUIRES_ACCOUNT`. Use `showsAccountSurfaces()` / `citationAuthorityAvailable()` from `src/community/gating.ts` to hide account-only chrome. Do not sprinkle `isCommunity()` through every card.
9. **Immutability:** create new objects, do not mutate. Small cohesive files. Validate user input.
10. **Customer-facing copy (hosted product):** do not name third-party model or infrastructure vendors. The community Settings / KeyWizard **must** name providers because the user picks one. README and DEPLOY may name them. In-app hosted copy says "HakiChain AI".
11. **Writing style:** US spelling. No emojis (lucide-style SVGs in `src/ui/icons.tsx` are fine). No em dashes. Use ASCII hyphen-minus, periods, or commas.
12. **Check `git status`** before assuming a feature is or is not landed.
13. **Roles** in product are only `owner` and `member`. Check `userRole === "owner"`. Never invent `admin` / `viewer`.
14. **Matter 404** means no access or not found. The backend uses 404, not 403, so it does not leak matter existence. Do not "fix" that to 403.

---

## Office.js gotchas

Full helpers: `src/office/`. Entry wrappers: `run.ts`.

**Tracked-change author is read-only.** In-pane edits while tracking is on are attributed to the signed-in Word user. For a branded author ("HakiChain AI Contract Review"), use the server export (`POST /api/v1/legal-tools/export-corrected`) and insert via `body.insertFileFromBase64`, not in-pane `insertText`.

**Redline apply** (`src/office/redline.ts`): remember prior `changeTrackingMode`, set `TrackAll`, locate verbatim `currentLanguage`, word-level diff via `office-word-diff`, restore mode, `sync()`. Word `body.search` is capped at **255 characters** and cannot cross a paragraph mark. Long / multi-paragraph clauses anchor on head + tail windows, then the span between them. `canApplyInPane` is true when there is verbatim current language to search for. Re-verify the located span at apply time (the backend "unverified" flag is stricter than the client's tolerant search: smart quotes, dashes, spacing). Insertions (missing clauses) are inserted at a chosen location, not searched for. Fall back to export-corrected or a copy/manual path when the pane cannot anchor (text boxes / shapes are invisible to `body.search`).

**Word on the web:** `insertOoxml` is unreliable. Prefer plain tracked `insertText`; fall back to server DOCX. `getTrackedChanges` can fail on moved changes. `TrackedChange.getRange` differs across hosts. Enumerate defensively: `getFirstOrNullObject` + `isNullObject`, never `getFirst`. `getFileAsync` can return 11001 on some web tenants. Always `closeAsync()` the file handle (`src/office/file.ts`). Default analysis uses the text `body` path; compressed `.docx` bytes are for compare / template upload.

**UI thread:** never block more than ~5 seconds. Office restarts the add-in and disables it after 4 crashes in a session. Long work is chunked or streamed.

**Protected / read-only documents:** `runWord` maps AccessDenied and a language-independent `DocumentProperties.security` check to a Restrict Editing message. Loops that swallow per-item failures must use `isProtectionError` and rethrow, or a redact/fill pass can silently report "not found" (a data-leak-grade lie).

**Manifests:** add-in-only **XML**, not the unified JSON manifest (JSON drops perpetual Office, Outlook on Mac, mobile). Floor WordApi 1.6; feature-detect 1.7 to 1.9. List every navigated domain in `<AppDomains>`. Ribbon icons must stay cacheable (no `no-store`).

---

## Authentication (hosted)

Office Dialog API + Supabase Authorization Code + PKCE. **Not** Office SSO / Nested App Authentication (Entra tokens are rejected by the Supabase-JWT backend).

Flow: pane `displayDialogAsync` -> same-origin `auth.html` -> PKCE in the isolated dialog webview -> `messageParent` of stringified access + refresh tokens (strings only; do not rely on shared `localStorage` between dialog and pane). Pane holds the access token in memory and persists **only** the refresh token at `hakichain.refreshToken`. Refresh is single-flight (rotation: two concurrent refreshes would burn the token).

First-run org picker uses the backend bootstrap user (`get_current_user_no_org` equivalent). Document / review / drafting calls use the full user gate.

Community: no Supabase. Keys live in add-in-origin localStorage (`src/ai/keys.ts`). Never write keys to Office Settings.

---

## API + SSE

All pane HTTP goes through `src/api/http.ts` (`request`, `requestForm`, `requestBinary`) or `src/api/sse.ts` (`postStream`). Defaults: 120s JSON timeout, 180s upload, 120s SSE idle (deep review can be silent for more than a minute). 401: one silent refresh + retry.

**Do not use `EventSource`.** Endpoints are POST and need `Authorization`. Do not use a `?_token=` query fallback.

SSE parsing must be CRLF-safe and tolerate `data:` with or without a trailing space. Flush the decoder tail. Ignore `:` heartbeats. Handle non-200 **before** reading the body (402 / 429 can precede the stream). A stream that ends without `done` is a truncation: throw and let the caller retry.

Two SSE dialects:

- Legal tools: often **no** `event:` line. Event name is inside JSON as `{"type":"init"|"progress"|"result"|"done"|"error"}`. `postStream` recovers `type` when the SSE event is still `message`.
- Chat (`POST /api/v1/stream/chat`): real `event:` lines (`thinking`, `sources`, `chunk`, `verification`, `done`, `error`, `heartbeat`). Generate a UUID `clientMessageId`, send it, persist the assistant message under that id. On `replace`, clear streamed text before the rewrite. On terminal `done`, replace streamed text with `corrected_content` when present.

Document size: pre-check the **200,000** character cap (`MAX_DOCUMENT_CHARS` in `src/api/contract-review.ts`) before posting a full-doc review.

---

## Error contract

Map backend failures to pane states via `src/api/errors.ts` (`ApiError` + `errorMessage`):

| Status / code | Pane behavior |
| --- | --- |
| 401 | Silent refresh + one retry. Membership/org 401 -> org picker |
| 402 (`quota_exceeded`, `legal_tool_monthly_limit`, `premium_quota_exceeded`) | Usage from quotas endpoint + upgrade prompt |
| 413 `document_too_large` (`limit_chars`) | Suggest reviewing a selection |
| 422 | Surface the legal-validity rejection reason |
| 404 | Not found or no access. Matter-shaped codes get the matter copy |
| Community unimplemented path | `REQUIRES_ACCOUNT` -> "Requires a HakiChain AI account" |

---

## Multi-tenancy

Trusted org is JWT-derived server-side, never body-derived. The pane sends `X-Organization-ID` from `src/lib/org.ts` when an org is selected. Backend verifies active membership and returns 401 on a stale or forged value. Omit the header to let the server resolve the default.

---

## Community edition

`isCommunity()` is true for the community Vite mode **or** hosted-build BYOK.

`src/community/localRouter.ts` matches path + method and returns the **same JSON shapes** as the backend so the ~35 `src/api/*.ts` modules stay untouched. `localStream.ts` emits the same SSE events. IndexedDB (`store.ts`) holds playbooks, prompts, clauses. Unimplemented hosted-only paths throw `REQUIRES_ACCOUNT`.

Community can: assistant, review/redlines, draft (no corpus / authorities / quality score), playbooks on-device, NDA triage, prompt/clause libraries, document tools, on-device compare (DOCX/TXT/MD), apply-all then download a tracked-changes copy, case-law **existence** if the user adds a CourtListener token.

Community cannot: good-law / treatment, statute corpus, branded server `export-corrected` author, compare hidden-revision detector, save to matters / vendors / the web app.

`setByokMode` returns whether the flag was **persisted**. If it returns false, do not reload the pane (reload would wipe the in-memory flag).

---

## Backend (this repo)

FastAPI in `backend/`. Prefix `/api/v1`. Health: `GET /health`, `GET /health/ready`.

| Router | Examples |
| --- | --- |
| `auth` | `GET /auth/me` |
| `legal_tools` | contract-review stream/classify/draft-fix, plain-english, risk, compliance, nda-triage, export-corrected, playbook-fit |
| `chat` | `POST /stream/chat` |
| `drafting` | generate, clause rewrite/explain, drafts, fill-from-reference, edit-document stream, redaction detect |
| `playbooks` | CRUD + extract-from-docx + learning/apply |
| `prompts` | prompt library CRUD |
| `research` | citation-style, citation-lookup, statutes, citation-status, compare (stubs / partial) |
| `shell` | quotas, matters, clients, templates, telemetry, notes, vendors |

MVP gaps (empty or not-found by design until filled): statute corpus, billed quotas, OCR jobs, some compare paths. Do not "fix" those by inventing fake corpus data.

Auth: Supabase JWT (JWKS, or `SUPABASE_JWT_SECRET` for older HS256). Tests use an in-memory store and a test JWT (`backend/tests/conftest.py`). Default pytest does not call a language model, CourtListener, or Supabase. Live checks: `pytest -m live` with `SMOKE_JWT` + `SMOKE_API` (see [docs/SMOKE.md](docs/SMOKE.md)).

---

## Config, hosting, CSP

- Hosted pane: `word.hakichain.com`. Hosted API: `api.hakichain.com`. `www.hakichain.com` is a different product.
- Community self-host: static `dist/` on any HTTPS host + a rewritten `manifest.community.xml`. See DEPLOY.md.
- Docker Compose: pane + API. Pane build args are **only** `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`.
- CSP `script-src` must allow `https://appsforoffice.microsoft.com`. `connect-src` must include the API + Supabase (hosted) or the user's providers (community). Hardened `deploy/nginx.conf` allowlists OpenAI, Anthropic, Groq, Gemini; Azure and Ollama hosts are per-deployment. `frame-ancestors` must permit Office web hosts.

---

## UI conventions

- White theme only. Tokens and primitives in `src/ui/`.
- Icons: add to `src/ui/icons.tsx`, do not drop raw emoji into the pane.
- Hosted login: no in-pane signup. Send people to `config.signupUrl`.
- Tours: `src/tour/`. Do not break `data-tour` anchors without updating the tour registry.

---

## Tests

| Suite | Command | Scope |
| --- | --- | --- |
| Pane unit | `npm run test` | `src/**/*.test.ts` (currently `src/api/errors.test.ts`). `src/ai/test.ts` is a provider ping, excluded from vitest |
| Backend unit | `cd backend && pytest -q` | In-memory store |
| Backend live | `pytest -m live` | Needs `SMOKE_JWT`, `SMOKE_API` |
| Types / bundle | `npm run type-check` && `npm run build` | Change gate |

Prefer a focused test next to the module (`foo.test.ts`) over a new framework.

---

## Where to look

| Task | Start here |
| --- | --- |
| Apply or find text in Word | `src/office/redline.ts`, `search.ts`, `anchor.ts`, `document.ts` |
| New backend call from the pane | add/extend `src/api/<surface>.ts`, then `http.ts` / `sse.ts`. If community should work, add a `localRouter` / `localStream` branch |
| New tab handoff | `src/app/nav.tsx` `AppIntent` |
| Auth / session | `src/auth/session.ts`, `dialog-login.ts` |
| BYOK providers | `src/ai/providers/`, `src/ai/keys.ts` |
| Review cards / sign-off | `src/features/review/`, render server gate as-is |
| Document tools | `src/features/toolshub/ToolsHub.tsx` + the feature folder |
| CSS | colocated `*.css` next to the view, plus `src/styles/` |
| Manifest / ribbon | `manifest*.xml` |
| API route | `backend/app/routers/` |
| Deploy / CSP | `DEPLOY.md`, `deploy/nginx.conf`, `Dockerfile` |

---

## Explicitly out of scope unless asked

- Committing, pushing, amending, or force-pushing
- Renaming the product or adding a dark theme
- Office SSO
- A second `Word.run` pipeline
- Putting secrets in the client bundle
- Recomputing approval gates on the client
- Expanding MVP backend stubs into a fake legal corpus

# CLAUDE.md

HakiChain for Microsoft Word. Vite + React 18 + TypeScript task pane, Office.js (WordApi 1.6 floor).

**Canonical agent brief:** [AGENTS.md](AGENTS.md). Read that first. This file is a short operational digest. If the two disagree, AGENTS.md wins, then update this file.

Two editions from one repo: **hosted** (Supabase JWT + FastAPI in `backend/`) and **community / BYOK** (`src/community/` + `src/ai/`, no account). The pane does not invent legal intelligence. It reads the open document, calls an API (or the local shim), and applies results as Word tracked changes, comments, content controls, and custom XML.

## Commands

```bash
npm install
cp .env.example .env
npx office-addin-dev-certs install
npm run dev                 # hosted pane -> http://localhost:8000
npm run dev:community
npm run sideload            # manifest.dev.xml
npm run type-check && npm run build
npm run test
cd backend && pytest -q
```

Change gate: green `type-check` + `build`. Do not commit, push, or amend without an explicit per-turn request. Check `git status` before assuming something is landed.

## App shell

Four tabs in `src/app/nav.tsx`: **assistant** (default), **review**, **draft**, **tools**. Review subs: redlines / changes / compare / citations / playbooks. Cross-feature handoffs use `navigate(tab, intent)` + `clearIntent()`. Extend `AppIntent`. Do not add a fifth primary tab unless asked.

## Layout

| Path | Rule |
| --- | --- |
| `src/office/` | Only place `Word.run` lives. Use `runWord` / `serializeTrackChanges`. |
| `src/api/` | Only HTTP/SSE client. Feature code does not `fetch` the backend. |
| `src/community/` | BYOK shim. Same JSON/SSE shapes as the backend, or `REQUIRES_ACCOUNT`. |
| `src/ai/` | Provider registry + BYOK key store (localStorage, never Office Settings). |
| `src/auth/` | Dialog PKCE. Access token in memory. Refresh token in add-in-origin localStorage. |
| `src/ui/` | Reuse primitives. White theme. Icons in `src/ui/icons.tsx`. |
| `backend/` | Hosted FastAPI, prefix `/api/v1`. `service_role` stays here only. |

`@/` maps to `src/`. Config in `src/config.ts`. No secrets in the client bundle.

## Hard rules

- Do not add a second `Word.run` path outside `src/office/`.
- Never write tokens, keys, or PII into `Office.Settings` (travels inside the `.docx`).
- Never put `SUPABASE_SERVICE_ROLE_KEY` in Vite env or pane Docker build args.
- Read documents via `readDocumentText()` (`getReviewedText(current)`), not `body.text`.
- Render `approvalGate`, `liabilityExposure`, `counterpartyMatch` as the server sent them.
- Roles are only `owner` and `member`. Matter 404 means no access or not found.
- Hosted customer-facing copy: do not name model vendors. Community Settings may, because the user picks a provider.
- US spelling. No emojis. No em dashes. Immutability. Validate input.

## Office.js (shortest form)

Tracked-change author is read-only: branded author requires server `export-corrected` + `insertFileFromBase64`. Search is 255 chars and cannot cross paragraphs (head/tail windows in `redline.ts`). Serialize tracking-mode flips. `getFirstOrNullObject`, never `getFirst`. Always `closeAsync()` file handles. Do not block the UI thread more than ~5s. Prefer `insertText` over `insertOoxml` on Word on the web.

## SSE

POST + `fetch` + reader. No `EventSource`. CRLF-safe. Legal-tool events may live in JSON `type`. Chat uses `event:` lines and `clientMessageId`. Non-200 before reading the body. No `done` means failure.

## Working style

Reuse `src/ui/` and `src/office/` before inventing. New community behavior goes in the shim, not as `isCommunity()` forks in every card. Details, endpoint map, and gotchas: [AGENTS.md](AGENTS.md).

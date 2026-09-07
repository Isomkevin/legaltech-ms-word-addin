# HakiChain AI backend (Word add-in MVP)

FastAPI service that implements the hosted API contract the Microsoft Word add-in already calls. In development the add-in talks to `http://localhost:8000` ([src/config.ts](../src/config.ts)).

This is the MVP: auth, contract review, assistant chat, clause tools, playbooks, and draft generation. Research corpus, billed quotas, OCR, compare, and branded tracked-changes export are out of scope and return empty or not-found shapes the pane already handles.

CORS allows exact origins with credentials: `https://localhost:3000`, `https://word.hakichain.ai`, and `https://word.hakichain.com`. Allowed request headers include `Authorization`, `Content-Type`, `X-Organization-ID`, and `X-Timezone`. The service does not send `X-Frame-Options: DENY`.

## Prerequisites

- Python 3.11+
- A Supabase project (the same one the add-in uses for login)
- An OpenAI-compatible API key (OpenAI, Groq, Azure, or a local server)

## Setup

1. Create a virtualenv and install dependencies:

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in:

- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (Project Settings, API). The service role stays here only. Never put it in the add-in.
- `SUPABASE_JWT_SECRET` if the project still issues HS256 access tokens. Newer projects use JWKS and can leave this blank.
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`

3. In the Supabase SQL editor, run [sql/001_init.sql](sql/001_init.sql). That creates `profiles`, `organizations`, `organization_members` (with non-recursive RLS so the add-in org switcher works), plus playbooks, drafts, analyses, and references.

4. Put the same project's URL and **anon** key in the add-in `.env` as `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`.

## Run

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then in the repo root: `npm run dev` and sideload the hosted (non-community) add-in. First sign-in creates a personal workspace automatically so Word users are not sent to a web signup.

## Tests

```bash
cd backend
pytest -q
```

Tests use an in-memory store and a test JWT secret. They do not call a language model or Supabase.

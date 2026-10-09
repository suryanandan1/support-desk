# AI-Powered Customer Support Automation System

A full-stack support platform. Customers ask questions in a chat, a Retrieval-Augmented
Generation (RAG) pipeline answers them with citations from company documents, and any
question the documents cannot support is turned into a support ticket for a human agent.

> **Status: Phase 1 of 10 complete.** Project foundation, configuration, the full
> database schema, and JWT authentication with role-based access control.
> AI answers, documents, and tickets arrive in later phases (see [Roadmap](#roadmap)).

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | SQLite for local development (PostgreSQL-compatible schema) |
| Auth | JWT access tokens (PyJWT), Argon2id password hashing |
| Frontend | React 19, Vite, Material UI 9, React Router 8, Axios |
| Tests | pytest + FastAPI TestClient, Vitest + Testing Library |
| Planned | Google Gemini (LLM + embeddings), FAISS, Celery + Memurai (Redis) |

## Quick start (Windows, PowerShell)

**Prerequisites:** Python **3.11** (some AI dependencies do not support 3.14 yet),
Node.js **22.22+** (tested on 24), Git.

> If `py` points to a newer Python on your machine, use `python` (3.11) or `py -3.11`
> explicitly when creating the virtual environment.

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Paste the printed value into SECRET_KEY= in backend\.env

alembic upgrade head          # create the database schema
python scripts\seed.py        # create demo accounts (see below)
uvicorn app.main:app --reload
```

- API: <http://127.0.0.1:8000/api/v1>
- Interactive API docs: <http://127.0.0.1:8000/docs>. Log in with `POST /auth/login`,
  then click **Authorize** and paste the `access_token`.

### 2. Frontend (second terminal)

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

### 3. Demo accounts

Created by `python scripts\seed.py`. All use the password `ChangeMe123!`
(pass `--password` to choose another). The script refuses to run when
`ENVIRONMENT=production`.

| Email | Role |
|---|---|
| admin@example.com | Admin |
| agent@example.com | Support agent |
| customer@example.com | Customer |

New sign-ups are always customers. Only an admin can grant the agent or admin role
(`PATCH /api/v1/users/{id}`).

### 4. Run the tests

```powershell
cd backend
pytest                 # 94 tests, uses throwaway databases, needs no API key

cd ..\frontend
npm test               # 54 component and unit tests
```

### 5. (Optional) Check your Gemini API key

Get a free key at <https://aistudio.google.com/apikey>, put it in `GEMINI_API_KEY` in
`backend\.env`, then run:

```powershell
python scripts\check_provider.py
```

It lists the chat and embedding models your key can access, and confirms that
`GEMINI_CHAT_MODEL` and `GEMINI_EMBEDDING_MODEL` exist.

## Configuration

All settings come from environment variables. See
[`backend/.env.example`](backend/.env.example) and
[`frontend/.env.example`](frontend/.env.example). Real values go in `backend\.env` and
`frontend\.env.local`, which are git-ignored. Never commit API keys.

## What Phase 1 includes

- **Authentication:** register, login, and `GET /auth/me`. Tokens expire after
  `ACCESS_TOKEN_EXPIRE_MINUTES`.
- **Backend-enforced roles:** every request reloads the user from the database, so a
  role change or deactivation takes effect immediately, even for tokens issued before it.
- **Admin user management:** list, search, and filter users; change roles; deactivate
  accounts. Admins cannot demote or deactivate themselves.
- **Complete data model:** users, conversations, messages, citations, documents,
  chunks, tickets, ticket messages (with internal notes), assignment history, feedback,
  and audit log, all created by one Alembic migration.
- **One error format:** every error looks like
  `{"error": {"code", "message", "details?", "request_id"}}`. Submitted values such as
  passwords are never echoed back.
- **Structured logging:** each request gets an id (also returned as the `X-Request-ID`
  header). Tokens, passwords, and API keys are redacted from all log output.
- **Audit log:** registrations, logins, failed logins, and user changes.

## Project layout

```
backend/
  app/
    api/            routes, dependencies (auth + roles), error handlers, middleware
    core/           settings, security (hashing, JWT), logging, domain exceptions
    db/             SQLAlchemy base, session, UTC datetime type
    models/         database tables
    repositories/   all database queries
    schemas/        Pydantic request/response models
    services/       business logic
    tests/          pytest suite
  alembic/          migrations
  scripts/          seed.py, check_provider.py
frontend/
  src/
    api/            Axios client and API calls
    components/     route guards, shared inputs
    contexts/       authentication state
    layouts/        auth card and responsive app shell
    pages/          Login, Register, Dashboard
    utils/          validation, error parsing, token storage
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. This only affects the current window. |
| `SECRET_KEY still has the placeholder value` or `at least 32 characters` | Generate a key with the command in step 1 and put it in `backend\.env`. |
| `no such table: users` | Run `alembic upgrade head` from the `backend` folder. |
| Browser console shows a CORS error | The frontend origin must be listed in `CORS_ORIGINS` in `backend\.env`. Restart the backend after changing it. |
| `Port 5173 is already in use` | Vite will not silently switch ports, because CORS only allows 5173. Stop the other process, or change the port in `vite.config.js` and add the new origin to `CORS_ORIGINS`. |
| `pip install` fails building a wheel | Make sure the virtual environment uses Python 3.11 (`python --version` with the venv active). |

## Roadmap

1. ~~Project setup, configuration, database, models, authentication~~ (done)
2. Document upload, text extraction, chunking, embeddings, FAISS index
3. RAG retrieval, grounded answers, source citations, evaluation
4. Conversation persistence, customer chat UI, feedback
5. Escalation rules, automatic tickets, customer ticket tracking
6. Agent dashboard, assignment, replies, ticket lifecycle
7. Admin knowledge-base interface and analytics
8. Background jobs (Celery + Memurai), retries, security hardening
9. Expanded tests, evaluation dataset, performance checks
10. Full Windows setup guide, architecture and API documentation

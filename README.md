# Auto CRM API

Backend for **Auto CRM**, an AI-assisted CRM. It uses FastAPI, async SQLAlchemy 2.1, PostgreSQL 17,
Alembic, DeepSeek (OpenAI-compatible) for AI features, and signed webhooks for n8n.

See `../PLAN.md` for the business requirements and the API contract.

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs and manages Python 3.14)
- Docker (for PostgreSQL, MinIO and Mailpit)

## Setup

```bash
cp .env.example .env            # skip if .env already exists; then fill in the values
docker compose up -d            # postgres:17, MinIO (:9100 / console :9101), Mailpit (SMTP :1026 / inbox :8026)
uv sync                         # create .venv and install dependencies
uv run alembic upgrade head     # create tables and seed the pipeline stages
uv run seed                     # optional: demo data (see "Demo data" below)
uv run fastapi dev src/app/main.py
```

- API: http://localhost:8000/api/v1
- Interactive docs (OpenAPI): http://localhost:8000/docs
- Health check: http://localhost:8000/health
- Sent emails (Mailpit): http://localhost:8026
- Uploaded images (MinIO console, `minioadmin` / `minioadmin`): http://localhost:9101

Put your DeepSeek key in `DEEPSEEK_API_KEY` in `.env`. Without a key, the `/ai/*` endpoints
return `503`.

> If port 5432 is already in use on your machine, set `POSTGRES_PORT` (e.g. `5433`) and use the
> same port in `DATABASE_URL`.

## Commands

| Task | Command |
| --- | --- |
| Run the dev server (auto-reload) | `uv run fastapi dev src/app/main.py` |
| Lint | `uv run ruff check .` (`--fix` to auto-fix) |
| Format | `uv run ruff format .` (`--check` in CI) |
| Type check | `uv run ty check` |
| Tests (all, with coverage) | `uv run pytest` |
| Unit tests only (no database needed) | `uv run pytest tests/unit --no-cov` |
| E2E tests (Newman) | `./e2e/run.sh` |
| Demo data | `uv run seed` (`--reset` to wipe and reseed) |
| Apply migrations | `uv run alembic upgrade head` |
| New migration from model changes | `uv run alembic revision --autogenerate -m "add x"` |
| Roll back one migration | `uv run alembic downgrade -1` |
| Add a dependency | `uv add <package>` (dev: `uv add --dev <package>`) |

## Demo data

`uv run seed` fills the database in `DATABASE_URL` with demo data: 4 users, 10 companies,
40 contacts, 25 deals in every stage, 60 activities, 30 tasks (some overdue, some done) and the two
n8n webhook subscriptions (inactive). Records are created through the services, so the normal rules
apply. The output is the same on every run (fixed Faker seed).

| User | Password | Role |
| --- | --- | --- |
| `admin@example.com` | `admin12345` | admin |
| `sarah@example.com`, `marco@example.com`, `priya@example.com` | `member12345` | member |

It refuses to run when the database already has data; `uv run seed --reset` empties the CRM tables
(pipeline stages and `alembic_version` are kept) and seeds again. It never seeds a database whose
name ends in `_test` or `_e2e`. The code is in `src/app/seed.py`.

## Tests

```
tests/
  conftest.py        # sets the test environment (DB name, API key, no AI key)
  unit/              # pure logic: services with mocked repositories, security, events,
                     # webhook signing/delivery (httpx mocked), AI client + prompts, schemas
  integration/       # HTTP requests against the app and a real database (+ the seeder)
```

- **Unit tests** never touch Postgres: `uv run pytest tests/unit --no-cov` runs in about a second.
  Services are built with a mocked session; `mock_repos(...)` swaps their repositories for
  `AsyncMock`s and the `make_*` factories in `tests/unit/conftest.py` build ORM objects in memory.
- **Integration tests** need the docker Postgres. They create (and recreate) a separate database
  called `auto_crm_test` on the same server, run the migrations against it, and truncate the tables
  after each test. AI calls are always faked; MinIO and SMTP are replaced by the in-memory
  `FakeStorage` / `FakeMailer` from `tests/fakes.py`.
- **Coverage** runs with every `uv run pytest` (configured in `pyproject.toml`, source `src/app`).
  The full suite must stay at 95% or more. The threshold only makes sense for the full suite, so
  pass `--no-cov` when running a subset.
- **E2E**: `./e2e/run.sh` runs the Postman collection with Newman against a real server on port
  8001 and a fresh `auto_crm_e2e` database, plus the real MinIO (bucket `auto-crm-e2e`) and Mailpit.
  See [`e2e/README.md`](e2e/README.md).

Images and email are described in [docs/12-files-and-email.md](../docs/12-files-and-email.md).

## Architecture

```
src/app/
  main.py          # app factory: CORS, exception handlers, routers, /health
  api.py           # includes every module router under /api/v1
  models.py        # imports all ORM models (so Alembic sees every table)
  core/            # config, database, security, exceptions, logging, events
  shared/          # Base model + mixins, Page[T] pagination, reference schemas, utils
  modules/
    <module>/
      router.py        # HTTP only: parse input, call the service, return a schema
      service.py       # business rules, transactions (commit), publishes events
      repository.py    # SQLAlchemy queries only
      models.py        # ORM tables
      schemas.py       # Pydantic request/response models
      dependencies.py  # FastAPI Depends helpers (e.g. ContactServiceDep)
  seed.py          # demo data (`uv run seed`)
migrations/        # Alembic (async env.py; schema + seed data migrations)
tests/             # unit/ and integration/
e2e/               # Postman collection + Newman runner
```

Modules: `auth users companies contacts pipeline deals activities tasks dashboard ai webhooks integrations`.

### Rules

- **Routers** never touch the database session. They call a service and return a response model.
- **Services** hold the business logic. They commit the transaction and publish events. They never
  import FastAPI `Request` or raise `HTTPException`.
- **Repositories** only run queries. Related rows are loaded explicitly with `joinedload(...)`:
  every relationship is `lazy="raise"`, so a forgotten load fails loudly instead of running a hidden query.
- **Errors**: services raise domain errors from `core/exceptions.py` (`NotFoundError`,
  `ConflictError`, `PermissionDeniedError`, ...). One handler turns them into `{"detail": "..."}`
  with the matching status code.

### Authentication

`get_current_user` (in `modules/auth/dependencies.py`) accepts either of these:

- `Authorization: Bearer <jwt>`: the token comes from `POST /auth/login`.
- `X-API-Key: <AUTOMATION_API_KEY>`: used by n8n. The request then acts as the service account
  `automation@auto-crm.local`, which is created automatically and cannot log in.

Use `CurrentUser` for any authenticated route, `AdminUser` for admin-only routes, and
`ServiceAccount` for API-key-only routes such as `POST /integrations/leads`.
The first user who registers becomes an admin; the service account does not count as that first user.

### Events and webhooks

Services call `events.publish(Event.X, data)` after commit. Each handler runs in its own
background asyncio task, so a failing handler is logged and never breaks the request.
`webhooks/delivery.py` is subscribed at startup. It POSTs to every active subscription for the
event:

```
POST <target_url>
X-AutoCRM-Event: deal.won
X-AutoCRM-Signature: sha256=<hex HMAC-SHA256 of the raw body, keyed by the subscription secret>

{"event": "deal.won", "occurred_at": "2026-01-01T12:00:00+00:00", "data": { ...DealRead... }}
```

`data` holds the resource in the same shape the API returns. `deal.stage_changed` also includes
`previous_stage: {id, name, is_won, is_lost}`.

### AI

`modules/ai/client.py` has a single `AIClient` (a thin wrapper over `AsyncOpenAI`) with
`complete_json(system=..., user=..., schema=...)`. It uses JSON mode and validates the reply with
Pydantic: an invalid reply returns `502`, and a missing key returns `503`. The prompts are in
`modules/ai/prompts.py`. `AIService` builds the context from the database.

## Response shapes (summary)

Use `/docs` for the full schema. Some conventions:

- Lists return `{items, total, page, size}`. Query parameters are `page` (default 1) and `size`
  (default 20, max 200), plus `search` and the module filters.
- Money (`value`, dashboard totals) is serialized as a JSON **number**.
- Responses include each foreign key id **and** a nested object. Send the `*_id` fields on
  create/update.
  - Company: `owner {id, full_name} | null`
  - Contact: `company {id, name} | null`, `owner {id, full_name} | null`, `ai_score`, `ai_summary`, `ai_scored_at`
  - Deal: `stage {id, name, is_won, is_lost}`, `contact {id, first_name, last_name} | null`,
    `company {id, name} | null`, `owner {id, full_name} | null`, `closed_at`
  - Activity: `created_by`, `contact`, `deal {id, title}` (each one can be null)
  - Task: `assignee`, `created_by`, `contact`, `deal` (each one can be null)
- `PATCH` updates only the fields you send. Sending `null` clears an optional field. Required fields
  (e.g. `first_name`, `title`) reject `null` with `422`.
- `GET /dashboard/summary`:
  ```json
  {
    "open_pipeline_value": 0, "won_this_month_value": 0,
    "new_leads_this_month": 0, "overdue_tasks": 0,
    "pipeline_by_stage": [{"stage_id": "…", "stage_name": "…", "deal_count": 0, "total_value": 0}],
    "recent_activities": [/* ActivityRead, latest 10 */],
    "my_tasks": [/* TaskRead, current user's open tasks, max 10 */]
  }
  ```

## Adding a module

1. Create `src/app/modules/<name>/` with `models.py`, `schemas.py`, `repository.py`, `service.py`,
   `dependencies.py` and `router.py`. Copy the pattern from `companies/`, the simplest full CRUD module.
2. Import the new model in `src/app/models.py`.
3. Include the router in `src/app/api.py`.
4. Run `uv run alembic revision --autogenerate -m "add <name>"`, review the file, then
   `uv run alembic upgrade head`.
5. Add unit tests for the service rules in `tests/unit/` and API tests in
   `tests/integration/test_<name>.py`.

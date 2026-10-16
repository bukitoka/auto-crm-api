# Auto CRM API

The backend for Auto CRM: a FastAPI app on PostgreSQL, with DeepSeek for the AI features and signed
webhooks for n8n.

## Run it

You need [uv](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env
docker compose up -d            # Postgres, MinIO (file storage) and Mailpit (test inbox)
uv sync
uv run alembic upgrade head
uv run seed                     # optional demo data
uv run fastapi dev src/app/main.py
```

The API is at http://localhost:8000 and its interactive docs at http://localhost:8000/docs.
Emails sent in development show up in Mailpit at http://localhost:8026.

The AI features need `DEEPSEEK_API_KEY` in `.env`; without it they answer `503` and everything
else still works. If port 5432 is taken on your machine, set `POSTGRES_PORT` (for example `5433`)
and use the same port in `DATABASE_URL`.

## Demo data

`uv run seed` creates a small sales team with companies, contacts, deals, activities and tasks.
It only runs on an empty database; `uv run seed --reset` wipes the CRM data and seeds again.

| Login | Password | Role |
| --- | --- | --- |
| `superadmin@example.com` | `superadmin12345` | super admin |
| `admin@example.com` | `admin12345` | admin |
| `sarah@example.com`, `marco@example.com`, `priya@example.com` | `member12345` | member |

## Commands

| Command | |
| --- | --- |
| `uv run pytest` | All tests (integration tests need the Docker Postgres) |
| `uv run pytest tests/unit --no-cov` | Unit tests only, no database |
| `./e2e/run.sh` | End-to-end run with Newman against a real server |
| `uv run ruff check . && uv run ruff format .` | Lint and format |
| `uv run ty check` | Type check |
| `uv run alembic revision --autogenerate -m "..."` | New migration |

Tests use their own databases (`auto_crm_test`, `auto_crm_e2e`), so your dev data is safe.

## How the code is organized

Each feature is a folder in `src/app/modules/` with the same files:

- `router.py` handles HTTP and calls the service.
- `service.py` holds the business rules, commits, and publishes events for webhooks.
- `repository.py` runs the queries.
- `models.py` and `schemas.py` are the tables and the request/response shapes.

Relationships are `lazy="raise"`, so a query that forgets to load related rows fails loudly instead
of running hidden queries. `companies/` is the simplest module to copy when adding a new one.

The super admin has every permission but isn't part of the team: it doesn't show up in user
lists, pickers or the dashboard. It is normally created on the web app's setup page, the first time
someone opens a new install. From the terminal:

```bash
uv run superadmin create --email you@example.com
uv run superadmin reset-password --email you@example.com   # works for any account
```

Both ask for the password, or read `SUPERADMIN_PASSWORD` when not run in a terminal.

Requests are authenticated with a JWT from `POST /auth/login`, or with the `X-API-Key` header for
n8n, which then acts as the `automation@auto-crm.local` service account.

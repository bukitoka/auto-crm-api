# Auto CRM API

The backend for Auto CRM: a FastAPI app on PostgreSQL, with DeepSeek for the AI features and signed
webhooks for n8n.

## Run it

You need [uv](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env
docker compose up -d            # Postgres and MinIO (file storage)
uv sync
uv run alembic upgrade head
uv run seed                     # optional demo data
uv run fastapi dev src/app/main.py
```

The API is at http://localhost:8000 and its interactive docs at http://localhost:8000/docs.
In development, emails go to Mailpit (inbox at http://localhost:8025) because `SMTP_HOST` is set. To test Brevo, empty `SMTP_HOST` and set `BREVO_API_KEY` and a verified `MAIL_FROM_EMAIL`.

The AI features need `DEEPSEEK_API_KEY` in `.env`; without it they answer `503` and everything
else still works. If port 5432 is taken on your machine, set `POSTGRES_PORT` (for example `5433`)
and use the same port in `DATABASE_URL`.

## Demo data

`uv run seed` creates a super admin and four admins, with companies, contacts, deals, activities and tasks.
It only runs on an empty database; `uv run seed --reset` wipes the CRM data and seeds again.

| Login | Password | Role |
| --- | --- | --- |
| `superadmin@example.com` | `superadmin12345` | super admin |
| `alex@example.com`, `sarah@example.com`, `marco@example.com`, `priya@example.com` | `admin12345` | admin |

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

The super admin reads every admin's data but can't change CRM records. It creates and deactivates
admins, and manages pipeline stages and webhooks. Admins see only their own records. There is no
public sign-up. The super admin isn't part of the team: it doesn't show up in user
lists or pickers. It is normally created on the web app's setup page, the first time
someone opens a new install. From the terminal:

```bash
uv run superadmin create --email you@example.com
uv run superadmin reset-password --email you@example.com   # works for any account
```

Both ask for the password, or read `SUPERADMIN_PASSWORD` when not run in a terminal.

Requests are authenticated with a JWT from `POST /auth/login`, or with the `X-API-Key` header for
n8n, which then acts as the `automation@auto-crm.local` service account. That account is unscoped
(it reads and writes every record), can't log in, and is hidden from the user list.

## Production
Deployed by `.github/workflows/deploy.yml` to a Docker host behind Caddy (automatic HTTPS), with Neon
Postgres, Neon object storage and Brevo email (SDK). Copy `.env.production.example`
to `~/apps/auto-crm-api/.env` on the server. With `ENVIRONMENT=production` the API refuses to start on
weak secrets, and disables `/docs`. The `/api/v1/emails/notify` endpoint lets n8n send mail through the same backend.

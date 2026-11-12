# Auto CRM API

**Track the relationship. Turn the conversation into a follow-up.**

[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](src/app/main.py)
[![Latest release](https://img.shields.io/github/v/release/bukitoka/auto-crm-api?sort=date)](https://github.com/bukitoka/auto-crm-api/releases/latest)
[![Coverage 98.53%](https://img.shields.io/badge/coverage-98.53%25-238636)](#checks)
[![CI and deployment](https://github.com/bukitoka/auto-crm-api/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/bukitoka/auto-crm-api/actions/workflows/deploy.yml)

The backend for Auto CRM brings contacts, companies, deals, and tasks into one FastAPI app.
Its DeepSeek assistant works through the same CRM services as the web app: it can find a
contact, move a deal, draft an email, or create the next task. Signed webhooks connect that
work to n8n.

[Run locally](#run-locally) · [Explore the API](#explore-the-api) · [Checks](#checks) · [Code map](#code-map) · [Production](#production)

## What you can build with it

| Work | What the API provides |
| --- | --- |
| Manage relationships | Contacts, companies, activity timelines, CSV imports and exports |
| Move deals forward | Pipeline stages, deal values, closing dates, tasks, and reminders |
| Ask the assistant | Saved conversations, file attachments, CRM actions, charts, and tables |
| Use focused AI features | Lead scoring, timeline summaries, email drafts, and contact extraction |
| Connect your workflows | Lead intake, signed webhook events for n8n, and email notifications |
| See the numbers | Pipeline summaries, monthly trends, overdue work, and team statistics |

## Run locally

You need **Python 3.14+**, [uv](https://docs.astral.sh/uv/), and Docker.

```bash
cp .env.example .env
# Edit .env and replace JWT_SECRET_KEY and AUTOMATION_API_KEY.
docker compose up -d --wait
uv sync
uv run alembic upgrade head
uv run seed                     # optional: create a workspace with demo data
uv run fastapi dev src/app/main.py
```

| Open | Local address |
| --- | --- |
| Interactive API docs | http://localhost:8000/docs |
| API health and version | http://localhost:8000/health |
| Mailpit inbox | http://localhost:8025 |
| MinIO console | http://localhost:9101 |

Docker runs PostgreSQL 17, MinIO, and Mailpit. The API runs on your host through uv.
If port `5432` is taken, change `POSTGRES_PORT` and the port in `DATABASE_URL` in `.env`.

Set `DEEPSEEK_API_KEY` to use the assistant and AI features. Without it, AI requests return
`503`; the rest of the CRM still works. Local email goes to Mailpit. To use Brevo instead,
empty `SMTP_HOST`, set `BREVO_API_KEY`, and set `MAIL_FROM_EMAIL` to a verified sender.

<details>
<summary>Try the seeded workspace</summary>

`uv run seed` creates one super admin and four admins, plus companies, contacts, deals,
activities, and tasks. It runs only on an empty database.

| Login | Password | Role |
| --- | --- | --- |
| `superadmin@example.com` | `superadmin12345` | Super admin |
| `alex@example.com`, `sarah@example.com`, `marco@example.com`, `priya@example.com` | `admin12345` | Admin |

To start over, `uv run seed --reset` **wipes the CRM data** before seeding again.

</details>

## Explore the API

Routes live under `/api/v1`; `/health` sits outside that prefix. Start at `/docs` to browse
request schemas and try endpoints against your local workspace.

Admins work with their own CRM records. The super admin can read every admin's records,
create or deactivate admins, and manage pipeline stages and webhooks, but cannot change
CRM records. There is no public sign-up, and the super admin is excluded from team lists
and assignment pickers.

| Client | Authentication |
| --- | --- |
| Web app | JWT from `POST /api/v1/auth/login` |
| n8n / automation | `X-API-Key` header using `AUTOMATION_API_KEY` |

The automation key acts as `automation@auto-crm.local`. This service account can read and
write every CRM record, cannot log in, and stays hidden from user lists.

Create the first super admin through the web app's setup page, or use the CLI:

```bash
uv run superadmin create --email you@example.com
uv run superadmin reset-password --email you@example.com
```

Both commands prompt for a password, or read `SUPERADMIN_PASSWORD` outside a terminal.
The reset command works for any account.

## Checks

[![Lint and format with Ruff](https://img.shields.io/badge/lint_%26_format-Ruff-D7FF64?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![Managed with uv](https://img.shields.io/badge/managed_with-uv-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)

The latest local run on **2026-11-12** passed **413 tests** with **98.53% statement coverage**.
The coverage badge records that local result and is updated manually. The suite
enforces a **95% minimum** in [pyproject.toml](pyproject.toml). The workflow badge above
reports GitHub Actions, including deployment; the Ruff and uv badges identify the tools used.

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

| For this task | Run |
| --- | --- |
| Quick unit-test loop, no database | `uv run pytest tests/unit --no-cov` |
| Full suite with coverage; needs PostgreSQL | `uv run pytest` |
| Format Python files | `uv run ruff format .` |
| End-to-end checks with Newman against a real server | `./e2e/run.sh` |
| Generate a database migration | `uv run alembic revision --autogenerate -m "describe the change"` |

Tests use separate databases: `auto_crm_test` and `auto_crm_e2e`.

## Code map

```text
src/app/
├── main.py          # App setup, middleware, lifespan, and health endpoint
├── api.py           # Feature router registration
├── core/            # Configuration, database, auth primitives, storage, and email
├── modules/         # CRM features, AI, assistant, and integrations
└── shared/          # Pagination, CSV, images, and shared schemas
```

Inside a feature, follow `router.py` → `service.py` → `repository.py`: HTTP handling,
business rules and commits, then database queries. `models.py` defines tables;
`schemas.py` defines request and response shapes. Start with
[companies](src/app/modules/companies/) for a small example.

The assistant keeps its model loop in `agent.py`, conversation persistence in `service.py`,
and tools grouped by responsibility in `tools/`. Relationships use `lazy="raise"`, so
missing relationship loads fail explicitly rather than issuing hidden queries.

## Production

[GitHub Actions](.github/workflows/deploy.yml) deploys to a Docker host behind Caddy for
HTTPS. Production uses Neon PostgreSQL, Neon object storage, and Brevo email.

Copy [.env.production.example](.env.production.example) to
`~/apps/auto-crm-api/.env` on the server. With `ENVIRONMENT=production`, the API rejects
weak secrets at startup and disables interactive API docs. Deploy versions use
`YYYY.MM.DD.N` (date and run number); `/health` reports the version and commit.

The `POST /api/v1/emails/notify` endpoint lets n8n send notifications through the same backend.

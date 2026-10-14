# E2E tests (Postman + Newman)

A Postman collection that walks through the whole API like a real user would, run with
[Newman](https://github.com/postmanlabs/newman) against a real server and database.

```bash
./e2e/run.sh
```

What `run.sh` does:

1. `docker compose up -d --wait postgres minio mailpit`
2. drops and recreates the `auto_crm_e2e` database (the dev database `auto_crm` is never touched)
3. `alembic upgrade head` against it
4. starts the API on **port 8001** with `DATABASE_URL` pointing at `auto_crm_e2e`,
   `AUTOMATION_API_KEY=e2e-api-key`, an empty `DEEPSEEK_API_KEY` and `S3_BUCKET=auto-crm-e2e`
   (uploads never touch the dev bucket)
5. waits for `/health`, then runs `bunx newman@6.2.1` with the `cli` and `junit` reporters
6. stops the API (also on failure) and exits with Newman's exit code

Reports: `e2e/results/junit.xml` and the API log `e2e/results/api.log` (gitignored).
Requirements: Docker, uv, and Bun (`bunx`). Port 8001 must be free.

## Files

| File | Purpose |
| --- | --- |
| `auto-crm.postman_collection.json` | The collection (Postman v2.1). Import it into Postman to explore or edit. |
| `e2e.postman_environment.json` | URLs (`localhost:8001`, Mailpit `localhost:8026`), the API key and the test users. |
| `fixtures/` | Files for upload tests: a PNG and a text file that is *not* an image. |
| `run.sh` | The full lifecycle above. |

## The story

The folders run in order and share IDs through collection variables
(`pm.collectionVariables.set(...)`):

Health → Auth (first user is admin, member, login, 401s) → Users (403/400 rules) →
Companies → Contacts (search, filters, 409 duplicate email, 422 validation) → Pipeline stages →
Deals (defaults, Won sets `closed_at`, reopening clears it, filters) → Activities → Tasks
(overdue filter, completing) → Dashboard (numbers match the records above) → AI (503 without a
key) → Webhooks (admin only) → Integrations (API-key lead intake 201/200, 401s) → Images & email
(upload to the real MinIO and download the WebP, 400 for non-images, removed file is 404; send an
email and find it through Mailpit's API; forgot password → read the link from the actual email →
reset → log in → reused link is 400) → Cleanup (delete everything, then 404s).

Emails are matched by a per-run id (`runId`), so other messages in the Mailpit inbox don't matter.

The collection expects an **empty** database: the first registered user must become the admin
and the dashboard checks exact totals. Always run it through `run.sh`.

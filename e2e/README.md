# End-to-end tests

A Postman collection that goes through the whole API the way users would: set up the super admin, create an admin, log in as that admin,
add companies and contacts, move deals, finish tasks, upload images, reset a password by email, and
clean up at the end. It also checks that the super admin gets 403 on CRM writes and that a
second admin gets 404 on the first admin's records.

```bash
./e2e/run.sh
```

The script starts Postgres and MinIO, creates a fresh `auto_crm_e2e` database, runs the
API on port 8001 and runs the collection with Newman. Your dev database and files are never
touched. You need Docker, uv and Bun, and port 8001 must be free.

Results end up in `e2e/results/` (`junit.xml` and the API log).

The collection expects an empty database, so always run it through `run.sh`. To explore or edit
it, import `auto-crm.postman_collection.json` and `e2e.postman_environment.json` into Postman.

"""Shared test setup.

Settings are read once, when `app` is first imported, so the environment is prepared
here before any test module imports the app:

- `DATABASE_URL` points at `auto_crm_test` (only the integration tests connect to it),
- the automation API key is a known test value,
- the DeepSeek key is empty (AI calls are always faked).
"""

import os
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
# Overridable so concurrent test runs can use separate databases.
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "auto_crm_test")
TEST_API_KEY = "test-automation-key"


def _test_database_url() -> str:
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    url = make_url(env.get("DATABASE_URL") or "postgresql+asyncpg://postgres:postgres@localhost/x")
    return url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)


os.environ["DATABASE_URL"] = _test_database_url()
os.environ["AUTOMATION_API_KEY"] = TEST_API_KEY
os.environ["DEEPSEEK_API_KEY"] = ""

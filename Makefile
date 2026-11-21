.DEFAULT_GOAL := help
.PHONY: help install services stop status dev migrate seed lint typecheck test unit check

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install runtime and dev dependencies from the lockfile
	uv sync --locked

services: ## Start PostgreSQL, MinIO, and Mailpit
	docker compose up -d --wait

stop: ## Stop the local containers
	docker compose stop

status: ## Show local container status
	docker compose ps

dev: ## Start FastAPI with reload
	uv run fastapi dev src/app/main.py

migrate: ## Apply database migrations
	uv run alembic upgrade head

seed: ## Load demo data into an empty local database
	uv run seed

lint: ## Check lint and formatting
	uv run ruff check src tests migrations
	uv run ruff format --check src tests migrations

typecheck: ## Check Python types
	uv run ty check

test: ## Run the full suite with coverage (requires PostgreSQL)
	uv run pytest

unit: ## Run unit tests without PostgreSQL
	uv run pytest tests/unit --no-cov

check: lint typecheck test ## Run the backend quality checks

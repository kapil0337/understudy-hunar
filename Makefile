.PHONY: up down logs seed test migrate gen-api fmt lint smoke-hunar capture-hunar-fixtures

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

seed:
	@echo "No fixtures defined yet — add data under backend/fixtures/ and wire up a seed script."

TEST_DSN = postgresql+asyncpg://understudy:understudy@localhost:5433/understudy_test

# The suite talks to TEST_DATABASE_URL and refuses to run if it equals DATABASE_URL, so pytest
# is never handed the latter. The alembic step is a separate process that migrates whatever
# DATABASE_URL points at — here, deliberately, the test database.
test:
	docker compose --profile test up -d --wait postgres-test
	cd backend && DATABASE_URL="$(TEST_DSN)" uv run alembic upgrade head
	cd backend && TEST_DATABASE_URL="$(TEST_DSN)" uv run pytest

migrate:
	docker compose exec backend alembic upgrade head

gen-api:
	curl -sf http://localhost:8000/openapi.json -o web/src/lib/api/openapi.json
	cd web && npm run gen-api

fmt:
	cd backend && uv run ruff format .
	cd web && npm run format

lint:
	cd backend && uv run ruff check . && uv run mypy app alembic tests scripts
	cd web && npm run lint

# Read-only connectivity check: prints agents, numbers and allowed_countries per number.
# Needs HUNAR_API_KEY in the environment.
smoke-hunar:
	cd backend && uv run python scripts/smoke_hunar.py

# Re-record tests/fixtures/hunar/ from the live API. Run this WHILE THE KEY IS STILL VALID —
# those fixtures are what keep the test suite runnable after it expires. Read-only and scrubbed.
capture-hunar-fixtures:
	cd backend && uv run python scripts/capture_hunar_fixtures.py

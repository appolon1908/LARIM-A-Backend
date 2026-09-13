.PHONY: setup dev test lint migrate seed worker clean openapi
setup:
	python3 scripts/local-env.py

dev:
	docker compose up --build -d

migrate:
	docker compose run --rm migrate

seed:
	docker compose exec api python scripts/seed.py

test:
	uv run --frozen --all-extras pytest -q

lint:
	uv run --frozen --all-extras ruff check src tests scripts migrations
	uv run --frozen --all-extras ruff format --check src tests scripts migrations
	uv run --frozen --all-extras mypy src

worker:
	uv run --frozen python -m larimia.marketplace.worker

openapi:
	uv run --frozen python scripts/export_openapi.py

clean:
	docker compose down

.PHONY: backend frontend test lint migrate mlflow

backend:
	uv run --directory backend --env-file ../.env uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	npm --prefix frontend run dev -- --hostname 127.0.0.1

test:
	uv run --directory backend --env-file ../.env pytest
	npm --prefix frontend test

lint:
	uv run --directory backend --env-file ../.env ruff check .
	uv run --directory backend --env-file ../.env ruff format --check .
	uv run --directory backend --env-file ../.env black --check .
	npm --prefix frontend run lint
	npm --prefix frontend run typecheck

migrate:
	uv run --directory backend --env-file ../.env alembic upgrade head

mlflow:
	uv run --directory backend --env-file ../.env mlflow ui --host 127.0.0.1 --port 5000

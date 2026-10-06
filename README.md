# AI Study Assistant

A syllabus-aligned study assistant for asking questions about course PDFs and
generating quizzes. The repository is being built incrementally; this scaffold
sets up the development environment without implementing authentication,
application database models, PDF ingestion, or NLP/ML features.

## Requirements

- Python 3.11 and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- GNU Make (optional; direct commands are shown below)

## Native development setup

1. Copy `.env.example` to `.env`. The default `BACKEND=local` uses SQLite,
   FastAPI BackgroundTasks, embedded Qdrant file storage, and files under
   `./storage`; no containers or external services are required.
2. Install dependencies:

   ```sh
   uv sync --directory backend
   npm --prefix frontend ci
   ```

3. Start the API and frontend in separate terminals:

   ```sh
   make backend
   make frontend
   ```

   The API is at <http://127.0.0.1:8000>, its health endpoint is
   <http://127.0.0.1:8000/health>, and the UI is at <http://127.0.0.1:3000>.
   Alternatively, run
   `uv run --directory backend --env-file ../.env uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
   and `npm --prefix frontend run dev -- --hostname 127.0.0.1`.

## Developer commands

`make backend`, `make frontend`, `make test`, `make lint`, `make migrate`, and
`make mlflow` provide native development commands. MLflow's local UI is
available at <http://127.0.0.1:5000>. Alembic starts with an empty initial
revision so the same migration command works with SQLite locally and a
PostgreSQL `DATABASE_URL` in production.

Set `BACKEND=prod` and configure `DATABASE_URL`, `QDRANT_URL`, and S3 settings
to select production adapters. Celery uses `REDIS_URL`; S3-compatible storage
uses `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, and
`S3_SECRET_ACCESS_KEY` (or the AWS SDK's default credential chain). Do not
commit credentials.

`backend/Dockerfile`, `frontend/Dockerfile`, `infra/Dockerfile`, and
`docker-compose.prod.yml` are deployment artifacts for use on a hosting
platform; Docker is not part of the development workflow.

To run checks without Docker:

```sh
cd backend
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run black --check .
uv run pytest

cd frontend
npm ci
npm run lint
npm run typecheck
npm test
```

See [the scaffold learning note](docs/learn/01-scaffold.md) for an overview and
viva questions. Project-wide instructions are in
`.github/copilot-instructions.md`.

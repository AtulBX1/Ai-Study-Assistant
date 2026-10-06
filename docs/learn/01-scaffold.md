# Step 1: Project scaffold and development environment

## What was built

The repository now has the main backend, frontend, ML, model, data,
documentation, and infrastructure folders. The FastAPI service has starter
routers, services, models, schemas, core configuration, and workers packages.
It exposes a health check, reads configuration from environment variables,
allows the local frontend through CORS, writes structured JSON logs, and
attaches a request ID to each response. Backend dependencies are locked with uv
for Python 3.11. The Next.js App Router frontend has a small landing page, a
reusable shadcn-style button, and an API client that checks backend health.

Native development uses SQLite through SQLAlchemy, FastAPI BackgroundTasks,
Qdrant's local file mode, and local file storage. A shared `BACKEND` setting
selects production adapters for PostgreSQL, Celery/Redis, Qdrant server, and
S3-compatible storage. Alembic has an initial migration revision and uses the
configured SQLAlchemy URL. MLflow runs locally with `mlflow ui`. Dockerfiles and
`docker-compose.prod.yml` are reserved for deployment on a hosting platform.
Developer commands, pre-commit hooks, CI checks, and project instructions are
also in place.

No authentication, application tables, PDF processing, or NLP/ML features are
part of this step. Alembic is wired for later use but there are no schema
migrations yet.

## Why it was built

A consistent local environment makes later features easier to test and
integrate. Local adapters avoid requiring containers or remote services during
development, while interfaces let deployment select scalable services without
changing application code. Environment-based settings keep configuration and
secrets out of source control.

## How it works

Copy `.env.example` to `.env`, install backend dependencies with uv and
frontend dependencies with npm, then run `make backend` and `make frontend` in
separate terminals. The API listens on port 8000 and the UI on port 3000. The
frontend calls `/health`; the backend returns `{"status":"ok"}` and echoes the
request's `X-Request-ID` or creates one when absent. Backend logs are JSON
records with the active request ID. Run `make migrate` to apply Alembic
migrations to the configured database, or `make mlflow` to start the local
tracking UI.

## Key syllabus concept

This step focuses on engineering foundations rather than an NLP algorithm:
modularity and reproducibility. A modular service layout and swappable adapters
help keep future text-processing, retrieval, and generation components
testable. Reproducible configuration and CI provide a dependable base for
evaluating those components.

## Viva questions

1. **Why use local adapters during development?**  
   They make the project runnable without containers or remote infrastructure,
   while interfaces allow production services to be plugged in later.

2. **What does the `/health` endpoint tell us?**  
   It confirms that the backend process is responding. It does not yet claim
   that every external dependency or application feature is ready.

3. **Why attach a request ID to a response and its logs?**  
   The same ID lets a developer correlate a client's request with the
   corresponding server log entries.

4. **Why keep secrets out of `.env.example` and source control?**  
   Tracked files are shared and retained; real credentials belong in a local
   ignored environment file or a managed secret store.

5. **What is the purpose of CI lint and test checks?**  
   They automatically catch style problems and regressions before changes are
   integrated, using repeatable checks on a clean runner.

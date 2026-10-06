param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("backend", "frontend", "test", "lint", "migrate", "mlflow")]
    [string]$Task
)

$ErrorActionPreference = "Stop"
$BackendPath = Join-Path $PSScriptRoot "backend"

Push-Location $BackendPath
try {
    switch ($Task) {
        "backend" {
            uv run --env-file ..\.env uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
        }
        "frontend" {
            Pop-Location
            npm --prefix frontend run dev -- --hostname 127.0.0.1
            Push-Location $BackendPath
        }
        "test" {
            uv run --env-file ..\.env pytest
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            Pop-Location
            npm --prefix frontend test
            Push-Location $BackendPath
        }
        "lint" {
            uv run --env-file ..\.env ruff check .
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            uv run --env-file ..\.env ruff format --check .
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            uv run --env-file ..\.env black --check .
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            Pop-Location
            npm --prefix frontend run lint
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            npm --prefix frontend run typecheck
            Push-Location $BackendPath
        }
        "migrate" {
            uv run --env-file ..\.env alembic upgrade head
        }
        "mlflow" {
            uv run --env-file ..\.env mlflow ui --host 127.0.0.1 --port 5000
        }
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

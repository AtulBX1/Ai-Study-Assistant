$ErrorActionPreference = "Stop"
Push-Location "$PSScriptRoot\..\backend"
uv run ruff check . ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
uv run ruff format --check . ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
uv run pytest -q ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
Pop-Location
Write-Host "CHECK PASSED"

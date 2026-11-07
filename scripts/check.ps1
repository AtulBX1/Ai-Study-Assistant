$ErrorActionPreference = "Stop"
. "$PSScriptRoot\env_d_cache.ps1"
Push-Location "$PSScriptRoot\..\backend"
uv run ruff check . ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
uv run ruff format --check . ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
cmd.exe /c 'uv run black --check . 2>&1' ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
uv run pytest ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
Pop-Location
Push-Location "$PSScriptRoot\..\frontend"
npm run lint ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
npm run typecheck ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
npm test ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
npm run build ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
npm run test:e2e ; if ($LASTEXITCODE) { Pop-Location; exit 1 }
Pop-Location
Write-Host "CHECK PASSED"

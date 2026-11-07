$ErrorActionPreference = "Stop"
$env:PLAYWRIGHT_BROWSERS_PATH = "D:\ml_cache\playwright"
$env:npm_config_cache = "D:\ml_cache\npm"
New-Item -ItemType Directory -Force -Path $env:PLAYWRIGHT_BROWSERS_PATH | Out-Null
New-Item -ItemType Directory -Force -Path $env:npm_config_cache | Out-Null

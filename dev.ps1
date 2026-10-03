<#
.SYNOPSIS
    Cross-platform Docker developer wrapper for VDaAgent.

.DESCRIPTION
    Use this script from Windows PowerShell instead of GNU make. It intentionally
    passes the project compose file explicitly so docker-compose.override.yml is
    never merged accidentally.
#>
[CmdletBinding()]
param(
    [ValidateSet('up', 'down', 'restart', 'logs', 'status', 'build', 'warehouse-check', 'help')]
    [string]$Command = 'help'
)

$ErrorActionPreference = 'Stop'
$ComposeFile = Join-Path $PSScriptRoot 'docker-compose.yml'
$EnvFile = Join-Path $PSScriptRoot '.env'
$RequiredKeys = @(
    'OPENAI_API_KEY',
    'OPENAI_BASE_URL',
    'LLM_MODEL',
    'VDAGENT_RE_WAREHOUSE_DB',
    'ORCH_SNAPSHOT_ID',
    'ORCH_SEMANTIC_VERSION'
)

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & docker compose -f $ComposeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE."
    }
}

function Get-EnvValue {
    param([Parameter(Mandatory)][string]$Name)

    $value = $null
    foreach ($line in Get-Content -LiteralPath $EnvFile) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*?)\s*$") {
            $value = $Matches[1] -replace '\s+#.*$', ''
            $value = $value.Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
    }
    return $value
}

function Assert-Configuration {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI was not found. Install Docker Desktop with Docker Compose v2.'
    }
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        throw 'MISSING .env -> run: Copy-Item .env.example .env, then fill in the required values.'
    }

    $missing = @($RequiredKeys | Where-Object { [string]::IsNullOrWhiteSpace((Get-EnvValue $_)) })
    if ($missing.Count -gt 0) {
        throw "EMPTY .env: $($missing -join ', ')"
    }

    $dsn = Get-EnvValue 'VDAGENT_RE_WAREHOUSE_DB'
    if ($dsn -notmatch '^postgres(ql)?://') {
        throw 'VDAGENT_RE_WAREHOUSE_DB must be a postgresql:// DSN. The product path never falls back to the synthetic warehouse; use docker compose --profile offline for tests.'
    }
    if ($dsn -match '@(127\.0\.0\.1|localhost|\[::1\])[:/]') {
        throw 'VDAGENT_RE_WAREHOUSE_DB points at localhost inside Docker. Use host.docker.internal for PostgreSQL on this Windows machine.'
    }
}

function Test-Agents {
    $agentCheck = "import json,sys,urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/api/agents', headers={'X-User-Id':'u_000000000001'}); got={a['name'] for a in json.load(urllib.request.urlopen(r))}; missing=set('orchestrator data compare insight report chart'.split())-got; print('agents loaded:', ' '.join(sorted(got))); missing and sys.exit('MISSING agents: ' + ' '.join(sorted(missing)))"
    Invoke-Compose @('exec', '-T', 'backend', 'python', '-c', $agentCheck)
}

function Start-Product {
    Assert-Configuration
    try {
        Invoke-Compose @('up', '-d', '--build', '--wait', 'backend')
    }
    catch {
        & docker compose -f $ComposeFile logs --no-log-prefix warehouse-check
        throw
    }
    Invoke-Compose @('logs', '--no-log-prefix', 'warehouse-check')
    Test-Agents
    $port = Get-EnvValue 'VDAGENT_PORT'
    if ([string]::IsNullOrWhiteSpace($port)) { $port = '8000' }
    Write-Host "VDaAgent is up: http://localhost:$port (UI and API)"
}

switch ($Command) {
    'up' { Start-Product }
    'down' { Invoke-Compose @('down') }
    'restart' { Invoke-Compose @('down'); Start-Product }
    'logs' { Invoke-Compose @('logs', '-f', 'backend') }
    'status' { Invoke-Compose @('ps') }
    'build' { Invoke-Compose @('build') }
    'warehouse-check' { Assert-Configuration; Invoke-Compose @('run', '--rm', 'warehouse-check') }
    default {
        Write-Host '.\dev.ps1 up                 build and start the product'
        Write-Host '.\dev.ps1 down               stop containers'
        Write-Host '.\dev.ps1 restart           restart the product'
        Write-Host '.\dev.ps1 logs              follow backend logs'
        Write-Host '.\dev.ps1 status            show status and health'
        Write-Host '.\dev.ps1 build             build images'
        Write-Host '.\dev.ps1 warehouse-check   validate warehouse reachability'
    }
}

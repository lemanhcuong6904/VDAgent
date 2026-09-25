$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $repoRoot '.env'

if (-not (Test-Path -LiteralPath $envFile)) {
    $bytes = [byte[]]::new(24)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $password = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    [System.IO.File]::WriteAllText($envFile, "POSTGRES_PASSWORD=$password`nPOSTGRES_DB=vdagent_dw_dev`n", [System.Text.UTF8Encoding]::new($false))
}

& docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker Engine is not running.' }

$names = @(& docker ps -a --format '{{.Names}}')
if ($LASTEXITCODE -ne 0) { throw 'Could not list Docker containers.' }
if ($names -contains 'vdagent-dw-dev') {
    & docker start vdagent-dw-dev *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start vdagent-dw-dev.' }
} else {
    & docker volume create vdagent_dw_dev_data *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not create PostgreSQL volume.' }
    & docker run -d --name vdagent-dw-dev --restart unless-stopped --env-file $envFile `
        -p '127.0.0.1:5434:5432' -v 'vdagent_dw_dev_data:/var/lib/postgresql/data' postgres:16-alpine *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not create PostgreSQL container.' }
}

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    & docker exec vdagent-dw-dev pg_isready -U postgres -d vdagent_dw_dev *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'PostgreSQL did not become ready.' }

$count = & docker exec vdagent-dw-dev psql -U postgres -d vdagent_dw_dev -At -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'dw' AND table_type = 'BASE TABLE';"
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect warehouse schema.' }
if ($count -eq '0') {
    & docker cp (Join-Path $repoRoot 'migrations\001_create_dw_v3_1_0.sql') 'vdagent-dw-dev:/tmp/migration.sql' *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy migration.' }
    & docker exec vdagent-dw-dev psql -U postgres -d vdagent_dw_dev -v ON_ERROR_STOP=1 -q -f /tmp/migration.sql
    if ($LASTEXITCODE -ne 0) { throw 'Migration failed.' }
} elseif ($count -ne '16') {
    throw "Unexpected warehouse table count: $count"
}

Write-Output 'PostgreSQL dev is ready at 127.0.0.1:5434; database vdagent_dw_dev; 16 warehouse tables.'

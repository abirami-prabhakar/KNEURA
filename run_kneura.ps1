param(
    [switch]$SaveConfig,
    [switch]$CheckOnly,
    [switch]$LoadOnly
)

$ErrorActionPreference = 'Stop'
$workspace = $PSScriptRoot
$configPath = Join-Path $workspace '.env.kneura.local'
$names = @('KNEURA_LLM_URL', 'KNEURA_LLM_MODEL', 'KNEURA_LLM_KEY', 'KNEURA_LLM_API_KEY', 'LLM_PROVIDER', 'LLM_TIMEOUT_SECONDS', 'LLM_MAX_RETRIES')

# Save only on explicit request, from the environment of the user's terminal.
# Never echo credentials, invoke env-file content, or pass secrets as arguments.
if ($SaveConfig) {
    $lines = @('# Private backend configuration. Never commit this file.')
    foreach ($name in $names) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if ($name -eq 'KNEURA_LLM_KEY' -and $null -eq $value) {
            $value = [Environment]::GetEnvironmentVariable('KNEURA_LLM_API_KEY', 'Process')
        }
        if ($null -eq $value) { $value = '' }
        if ($value -match '[\r\n\x00]') { throw "Invalid control character in $name." }
        if (($name -eq 'KNEURA_LLM_URL' -or $name -eq 'KNEURA_LLM_MODEL') -and [string]::IsNullOrWhiteSpace($value)) {
            throw "Set $name in this terminal before saving configuration."
        }
        if ($name -eq 'LLM_TIMEOUT_SECONDS' -and !$value) { $value = '30' }
        if ($name -eq 'LLM_MAX_RETRIES' -and !$value) { $value = '2' }
        if ($name -eq 'LLM_PROVIDER' -and !$value) { $value = 'chat-completions-compatible' }
        $lines += "$name=$value"
    }
    [IO.File]::WriteAllLines($configPath, $lines, [Text.UTF8Encoding]::new($false))
    Write-Output 'Saved private backend configuration to .env.kneura.local (credential hidden).'
}

# Explicit process variables take precedence over the saved backend env file.
# This deliberately does not load the frontend .env.local.
if (Test-Path -LiteralPath $configPath) {
    foreach ($line in [IO.File]::ReadAllLines($configPath)) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith('#')) { continue }
        $parts = $line -split '=', 2
        if ($parts.Count -ne 2 -or $names -notcontains $parts[0]) { throw 'Invalid entry in backend configuration file.' }
        if ($null -eq [Environment]::GetEnvironmentVariable($parts[0], 'Process')) {
            [Environment]::SetEnvironmentVariable($parts[0], $parts[1], 'Process')
        }
    }
}

Push-Location -LiteralPath $workspace
try {
    if ($CheckOnly) {
        & python -B scripts/check_kneura_config.py --health
        if ($LASTEXITCODE -ne 0) { throw 'LLM health check failed. See the credential-free result above.' }
    } else {
        & python -B scripts/check_kneura_config.py
        if ($LASTEXITCODE -ne 0) { throw 'Backend LLM configuration is incomplete or invalid.' }
        if (!$LoadOnly) {
            & python -B -m uvicorn backend.app:app --host 127.0.0.1 --port 8001
            if ($LASTEXITCODE -ne 0) { throw 'Backend stopped with an error.' }
        }
    }
} finally {
    Pop-Location
}

param(
    [Parameter(Mandatory = $true)][ValidateSet('Plan', 'ValidateEvidence')][string]$Mode,
    [Parameter(Mandatory = $true)][guid]$VmId,
    [Parameter(Mandatory = $true)][string]$Archive,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$EvidenceFile
)

# Controlador de preparação/validação. Não inicia VM, executa guestcontrol nem
# suspende o host. A transição real exige operador/driver no convidado.
$ErrorActionPreference = 'Stop'
function Test-NonnegativeJsonInteger($Record, [string]$Name) {
    $property = $Record.PSObject.Properties[$Name]
    if ($null -eq $property) { return $false }
    $value = $property.Value
    return (($value -is [int] -or $value -is [long]) -and $value -ge 0)
}
$acceptanceExit = 1
$summary = [ordered]@{
    schema_version = 1
    vm_id = $VmId.ToString()
    package_sha256 = $ExpectedSha256.ToLowerInvariant()
    status = 'pending'
    evidence_level = 'operator-recorded-vm'
    hardware_certified = $false
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
}
try {
    if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) { throw 'ARCHIVE_MISSING' }
    if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne $ExpectedSha256) {
        throw 'PACKAGE_HASH_MISMATCH'
    }
    $cases = @([ordered]@{ id = 'distribution'; kind = 'distribution'; status = 'pending' })
    foreach ($power in @('suspend', 'hibernate')) {
        foreach ($state in @('running', 'paused')) {
            foreach ($view in @('timer', 'history')) {
                foreach ($window in @('normal', 'minimized')) {
                    foreach ($theme in @('light', 'dark')) {
                        $cases += [ordered]@{
                            id = "power-$power-$state-$view-$window-$theme"
                            kind = 'guest-power'
                            power = $power; state = $state; view = $view
                            window = $window; theme = $theme; status = 'pending'
                        }
                    }
                }
            }
        }
    }
    $summary.cases = $cases
    if ($Mode -eq 'Plan') {
        $summary.reason_code = 'EXTERNAL_EXECUTOR_REQUIRED'
        $summary.next_steps = @(
            'Identificar a VM pelo UUID; registrar Windows 10/11 x64 e sessão gráfica.',
            'Transferir o ZIP completo; conferir SHA-256 dentro do convidado.',
            'Consultar powercfg /a dentro do convidado; não habilitar estados automaticamente.',
            'Usar perfil local temporário com dados sintéticos; conferir ausência de Python.',
            'Desconectar somente a rede do convidado e executar o roteiro de distribuição.',
            'Para energia, preparar o caso na VM e solicitar a transição no Windows convidado.',
            'Supervisionar e acordar a VM a partir do host com prazo máximo; não usar pause/savestate como prova de S3/S4.',
            'Registrar os resultados e validar a evidência, sem publicar banco ou logs pessoais.'
        )
        $acceptanceExit = 2
    }
    else {
        if (-not $EvidenceFile -or -not (Test-Path -LiteralPath $EvidenceFile -PathType Leaf)) {
            throw 'EVIDENCE_MISSING'
        }
        $evidence = Get-Content -LiteralPath $EvidenceFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($evidence.schema_version -ne 1 -or
            [string]$evidence.vm_id -ne $VmId.ToString() -or
            [string]$evidence.package_sha256 -ne $ExpectedSha256.ToLowerInvariant()) {
            throw 'EVIDENCE_IDENTITY_MISMATCH'
        }
        if (@('Windows 10', 'Windows 11') -notcontains [string]$evidence.environment.windows -or
            $evidence.environment.architecture -ne 'x64') { throw 'ENVIRONMENT_UNSUPPORTED' }
        foreach ($flag in @('python_absent', 'offline', 'isolated_profile', 'powercfg_checked')) {
            $value = $evidence.environment.$flag
            if ($value -isnot [bool] -or -not $value) { throw 'ENVIRONMENT_UNVERIFIED' }
        }
        $knownIds = @($cases | ForEach-Object { $_.id })
        $seen = @{}
        foreach ($result in @($evidence.results)) {
            if ($knownIds -notcontains [string]$result.id -or $seen.ContainsKey([string]$result.id)) {
                throw 'CASE_UNKNOWN_OR_DUPLICATE'
            }
            if (@('passed', 'failed', 'pending', 'unsupported') -notcontains [string]$result.status) {
                throw 'CASE_STATUS_INVALID'
            }
            $seen[[string]$result.id] = $result
            if ($result.status -ne 'passed') { continue }
            $flags = if ($result.id -eq 'distribution') {
                @('hash_verified', 'types_cycle', 'history_filters', 'theme_persisted',
                  'reopen_preserved', 'migration_preserved', 'directory_replacement')
            } else {
                @('guest_transition_confirmed', 'power_event_received', 'sleep_excluded',
                  'paused_after_resume', 'explicit_resume_only', 'reopen_preserved')
            }
            foreach ($flag in $flags) {
                $value = $result.$flag
                if ($value -isnot [bool] -or -not $value) { throw 'PASSED_CASE_WITHOUT_EVIDENCE' }
            }
            if ($result.id -ne 'distribution') {
                $requiredTransition = if ($result.id -like 'power-hibernate-*') { 'guest_s4' } else { 'guest_sleep' }
                foreach ($number in @('open_intervals_after', 'frozen_total_s',
                    'total_after_resume_s', 'total_after_observation_s')) {
                    if (-not (Test-NonnegativeJsonInteger $result $number)) {
                        throw 'POWER_RESULT_INCONSISTENT'
                    }
                }
                if ($result.transition -ne $requiredTransition -or
                    $result.open_intervals_after -ne 0 -or
                    $result.frozen_total_s -ne $result.total_after_resume_s -or
                    $result.total_after_resume_s -ne $result.total_after_observation_s) {
                    throw 'POWER_RESULT_INCONSISTENT'
                }
            }
        }
        foreach ($case in $cases) {
            if ($seen.ContainsKey($case.id)) { $case.status = [string]$seen[$case.id].status }
        }
        $summary.environment = [ordered]@{
            windows = [string]$evidence.environment.windows
            architecture = 'x64'; python_absent = $true; offline = $true
            isolated_profile = $true; powercfg_checked = $true
        }
        $states = @($cases | ForEach-Object { $_.status })
        if ($states -contains 'failed') {
            $summary.status = 'failed'
            $summary.reason_code = 'CASE_FAILED'
            $acceptanceExit = 1
        } elseif ($states -contains 'pending' -or $states -contains 'unsupported') {
            $summary.reason_code = 'COVERAGE_INCOMPLETE'
            $acceptanceExit = 2
        } else {
            $summary.status = 'evidence-complete'
            $summary.reason_code = 'OPERATOR_EVIDENCE_VALIDATED'
            $acceptanceExit = 0
        }
    }
}
catch {
    $summary.status = 'failed'
    $knownCodes = @('ARCHIVE_MISSING','PACKAGE_HASH_MISMATCH','EVIDENCE_MISSING',
        'EVIDENCE_IDENTITY_MISMATCH','ENVIRONMENT_UNSUPPORTED','ENVIRONMENT_UNVERIFIED',
        'CASE_UNKNOWN_OR_DUPLICATE','CASE_STATUS_INVALID','PASSED_CASE_WITHOUT_EVIDENCE',
        'POWER_RESULT_INCONSISTENT')
    $summary.reason_code = if ($knownCodes -contains $_.Exception.Message) {
        $_.Exception.Message
    } else { 'ACCEPTANCE_VALIDATION_FAILED' }
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (
    Join-Path $OutputDirectory 'windows-acceptance.json') -Encoding UTF8
Write-Output ("Aceite Windows: " + $summary.status + " (" + $summary.reason_code + ").")
exit $acceptanceExit

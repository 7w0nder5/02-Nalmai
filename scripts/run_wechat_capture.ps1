$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv-wechat\Scripts\python.exe"
$sourceRoot = Join-Path $projectRoot "tools\wechat_capture\src"
$nalmaiSourceRoot = Join-Path $projectRoot "src"
$envFile = Join-Path $projectRoot ".env"
$sharedAssetRoot = Join-Path $projectRoot "runtime\AstrBot-4.28.2\data\plugin_data\astrbot_plugin_nalmai\shared_assets"
$proxyName = "Nalmai-WeChat-Capture"
$listenPort = 8080

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [string]$Default = ""
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Nalmai .env does not exist."
    }
    $line = Get-Content -LiteralPath $Path -Encoding UTF8 |
        Where-Object { $_ -match ('^' + [regex]::Escape($Key) + '=') } |
        Select-Object -First 1
    if (-not $line) {
        return $Default
    }
    return $line.Substring($Key.Length + 1).Trim()
}

function Get-YamlScalar {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Key
    )

    $match = [regex]::Match(
        $Text,
        "(?m)^" + [regex]::Escape($Key) + ":\s*(.*?)\s*$"
    )
    if (-not $match.Success) {
        throw "Clash configuration field is missing: $Key"
    }
    return $match.Groups[1].Value.Trim().Trim("'").Trim('"')
}

function Invoke-ClashPipeRequest {
    param(
        [Parameter(Mandatory = $true)][string]$PipeName,
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$RequestPath,
        [Parameter(Mandatory = $true)][string]$Secret,
        [string]$Body = ""
    )

    $pipe = [System.IO.Pipes.NamedPipeClientStream]::new(
        ".",
        $PipeName,
        [System.IO.Pipes.PipeDirection]::InOut,
        [System.IO.Pipes.PipeOptions]::None
    )
    try {
        $pipe.Connect(3000)
        $utf8 = [System.Text.UTF8Encoding]::new($false)
        $bodyBytes = $utf8.GetBytes($Body)
        $headers = @(
            "$Method $RequestPath HTTP/1.1",
            "Host: localhost",
            "Authorization: Bearer $Secret",
            "Content-Type: application/json",
            "Content-Length: $($bodyBytes.Length)",
            "Connection: close",
            "",
            ""
        ) -join "`r`n"
        $headerBytes = [System.Text.Encoding]::ASCII.GetBytes($headers)
        $pipe.Write($headerBytes, 0, $headerBytes.Length)
        if ($bodyBytes.Length -gt 0) {
            $pipe.Write($bodyBytes, 0, $bodyBytes.Length)
        }
        $pipe.Flush()

        $buffer = New-Object byte[] 8192
        $response = New-Object System.IO.MemoryStream
        do {
            $read = $pipe.Read($buffer, 0, $buffer.Length)
            if ($read -gt 0) {
                $response.Write($buffer, 0, $read)
            }
        } while ($read -gt 0)
        $responseText = $utf8.GetString($response.ToArray())
        $statusMatch = [regex]::Match($responseText, '^HTTP/1\.[01]\s+(\d{3})')
        if (-not $statusMatch.Success) {
            throw "Clash control pipe returned an invalid HTTP response."
        }
        return [int]$statusMatch.Groups[1].Value
    }
    finally {
        $pipe.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Capture environment is missing. Run scripts\setup_wechat_capture.ps1 first."
}

$internalApiToken = Get-EnvValue -Path $envFile -Key "NALMAI_INTERNAL_API_TOKEN"
if (-not $internalApiToken) {
    throw "NALMAI_INTERNAL_API_TOKEN is missing from .env."
}
$localApiPort = Get-EnvValue `
    -Path $envFile `
    -Key "NALMAI_LOCAL_API_PORT" `
    -Default "8000"
if ($localApiPort -notmatch '^\d+$') {
    throw "NALMAI_LOCAL_API_PORT must contain only digits."
}

$occupied = Get-NetTCPConnection -State Listen -LocalPort $listenPort -ErrorAction SilentlyContinue
if ($occupied) {
    throw "Local port $listenPort is already in use. Close that program and retry."
}

try {
    $core = Get-CimInstance Win32_Process -Filter "Name='verge-mihomo.exe'" |
        Select-Object -First 1
}
catch {
    throw "Cannot inspect Clash Verge. Reopen PowerShell as administrator and retry."
}
if (-not $core) {
    throw "Clash Verge core is not running. Start Clash Verge and retry."
}

$configMatch = [regex]::Match(
    $core.CommandLine,
    '-f\s+(?:"([^"]+)"|(.+?))\s+-ext-ctl-pipe'
)
$pipeMatch = [regex]::Match(
    $core.CommandLine,
    '-ext-ctl-pipe\s+\\\\\.\\pipe\\([^\s"]+)'
)
if (-not $configMatch.Success -or -not $pipeMatch.Success) {
    throw "Clash Verge startup parameters do not contain the active config and control pipe."
}

$activeConfig = if ($configMatch.Groups[1].Success) {
    $configMatch.Groups[1].Value
} else {
    $configMatch.Groups[2].Value.Trim()
}
$pipeName = $pipeMatch.Groups[1].Value
if (-not (Test-Path -LiteralPath $activeConfig)) {
    throw "The active Clash configuration file does not exist."
}

$original = [System.IO.File]::ReadAllText($activeConfig)
if ($original.Contains($proxyName)) {
    throw "The active Clash configuration already contains the Nalmai temporary entry."
}
$secret = Get-YamlScalar -Text $original -Key "secret"
$proxyHeaderMatches = [regex]::Matches($original, '(?m)^proxies:\s*$')
$ruleHeaderMatches = [regex]::Matches($original, '(?m)^rules:\s*$')
if ($proxyHeaderMatches.Count -ne 1 -or $ruleHeaderMatches.Count -ne 1) {
    throw "The active Clash configuration must contain exactly one proxies and one rules section."
}

$lineEnding = if ($original.Contains("`r`n")) { "`r`n" } else { "`n" }
$proxyBlock = @(
    "- name: $proxyName",
    "  type: http",
    "  server: 127.0.0.1",
    "  port: $listenPort"
) -join $lineEnding
$ruleBlock = "- AND,((DOMAIN,tgk-wcaime.wahlap.com),(DST-PORT,80)),$proxyName"
$proxyRegex = New-Object regex '(?m)^proxies:\s*$'
$ruleRegex = New-Object regex '(?m)^rules:\s*$'
$temporaryConfigText = $proxyRegex.Replace(
    $original,
    "proxies:$lineEnding$proxyBlock",
    1
)
$temporaryConfigText = $ruleRegex.Replace(
    $temporaryConfigText,
    "rules:$lineEnding$ruleBlock",
    1
)

$configDirectory = Split-Path -Parent $activeConfig
$temporaryConfig = Join-Path $configDirectory (
    "clash-verge-nalmai-" + [guid]::NewGuid().ToString('N') + ".yaml"
)
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$loadedTemporaryConfig = $false
$captureExit = 1

try {
    [System.IO.File]::WriteAllText(
        $temporaryConfig,
        $temporaryConfigText,
        $utf8NoBom
    )

    $validationOutput = & $core.ExecutablePath -t -d $configDirectory -f $temporaryConfig 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "The temporary Clash configuration failed validation."
    }

    $loadBody = @{ path = $temporaryConfig } | ConvertTo-Json -Compress
    $loadStatus = Invoke-ClashPipeRequest `
        -PipeName $pipeName `
        -Method "PUT" `
        -RequestPath "/configs?force=true" `
        -Secret $secret `
        -Body $loadBody
    if ($loadStatus -ne 204) {
        throw "Clash refused the temporary configuration (HTTP $loadStatus)."
    }
    $loadedTemporaryConfig = $true

    Write-Host "Nalmai temporary callback rule is active."
    Set-Location -LiteralPath $projectRoot
    $env:PYTHONPATH = "$sourceRoot;$nalmaiSourceRoot"
    $env:NALMAI_INTERNAL_API_TOKEN = $internalApiToken
    $env:NALMAI_LOCAL_API_URL = "http://127.0.0.1:$localApiPort"
    & $python -m nalmai_wechat_capture.main `
        --proxy-mode regular `
        --listen-host 127.0.0.1 `
        --listen-port $listenPort `
        --shared-output $sharedAssetRoot `
        --wait-for-enter
    $captureExit = $LASTEXITCODE
}
finally {
    $env:NALMAI_INTERNAL_API_TOKEN = $null
    $env:NALMAI_LOCAL_API_URL = $null
    if ($loadedTemporaryConfig) {
        try {
            $restoreBody = @{ path = $activeConfig } | ConvertTo-Json -Compress
            $restoreStatus = Invoke-ClashPipeRequest `
                -PipeName $pipeName `
                -Method "PUT" `
                -RequestPath "/configs?force=true" `
                -Secret $secret `
                -Body $restoreBody
            if ($restoreStatus -ne 204) {
                throw "Unexpected restore status: $restoreStatus"
            }
            Write-Host "The original Clash configuration has been restored."
        }
        catch {
            Write-Warning "Clash restore failed. Reload the current profile in Clash Verge."
        }
    }
    if (Test-Path -LiteralPath $temporaryConfig) {
        Remove-Item -LiteralPath $temporaryConfig -Force
    }
}

exit $captureExit

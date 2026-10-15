$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Get-LocalTcpRows {
    $netstatPath = Join-Path $env:SystemRoot "System32\netstat.exe"
    foreach ($line in (& $netstatPath -ano -p tcp 2>$null)) {
        if ($line -match '^\s*TCP\s+(?<local>\S+):(?<localPort>\d+)\s+(?<remote>\S+):(?<remotePort>\d+)\s+(?<state>\S+)\s+(?<processId>\d+)\s*$') {
            [pscustomobject]@{
                LocalAddress = $Matches.local
                LocalPort = [int]$Matches.localPort
                RemoteAddress = $Matches.remote
                RemotePort = [int]$Matches.remotePort
                State = $Matches.state
                OwningProcess = [int]$Matches.processId
            }
        }
    }
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$astrDir = Join-Path $projectRoot "runtime\AstrBot-4.28.2"
$astrPython = Join-Path $astrDir ".venv\Scripts\python.exe"
$napDir = Join-Path $projectRoot "runtime\NapCat-Shell-4.18.28"
$napLauncher = Join-Path $napDir "launcher.bat"
$runtimeState = Join-Path $projectRoot "runtime\nalmai-state"
$pidFile = Join-Path $runtimeState "astrbot.pid"
$logDir = Join-Path $astrDir "logs"
$stdoutLog = Join-Path $logDir "astrbot.active.stdout.log"
$stderrLog = Join-Path $logDir "astrbot.active.stderr.log"

foreach ($required in @($astrPython, (Join-Path $astrDir "main.py"), $napLauncher)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing runtime file: $required"
    }
}

New-Item -ItemType Directory -Path $runtimeState -Force | Out-Null
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$astrPorts = @(6185, 6199)
$astrListeners = @(Get-LocalTcpRows |
    Where-Object { $_.State -eq "LISTENING" -and $_.LocalAddress -eq "127.0.0.1" -and $_.LocalPort -in $astrPorts })
$astrListeningPorts = @($astrListeners | Select-Object -ExpandProperty LocalPort -Unique)
$astrOwners = @($astrListeners | Select-Object -ExpandProperty OwningProcess -Unique)

if ($astrListeningPorts.Count -eq 2 -and $astrOwners.Count -eq 1) {
    $astrPid = $astrOwners[0]
    Set-Content -LiteralPath $pidFile -Value $astrPid -Encoding ASCII
    Write-Host "AstrBot is already running (PID $astrPid)."
} elseif ($astrListeners.Count -gt 0) {
    throw "AstrBot port conflict detected on 127.0.0.1:6185 or 127.0.0.1:6199."
} else {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $astrProcess = Start-Process -FilePath $astrPython `
        -ArgumentList "main.py" `
        -WorkingDirectory $astrDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
    $astrReady = $false
    $astrOwner = $null
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        $listeners = @(Get-LocalTcpRows |
            Where-Object { $_.State -eq "LISTENING" -and $_.LocalAddress -eq "127.0.0.1" -and $_.LocalPort -in $astrPorts })
        $listeningPorts = @($listeners | Select-Object -ExpandProperty LocalPort -Unique)
        $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
        if ($listeningPorts.Count -eq 2 -and $owners.Count -eq 1) {
            $astrReady = $true
            $astrOwner = $owners[0]
            break
        }
    }
    if (-not $astrReady) {
        throw "AstrBot did not start within 45 seconds. Check: $stderrLog"
    }
    Set-Content -LiteralPath $pidFile -Value $astrOwner -Encoding ASCII
    Write-Host "AstrBot started (PID $astrOwner)."
}

$napProcess = Get-Process -Name "NapCatWinBootMain" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq (Join-Path $napDir "NapCatWinBootMain.exe") } |
    Select-Object -First 1

if ($napProcess) {
    Write-Host "NapCat is already running (PID $($napProcess.Id))."
} else {
    Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" `
        -ArgumentList "/k", "launcher.bat" `
        -WorkingDirectory $napDir | Out-Null

    $napReady = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        $listener = Get-LocalTcpRows |
            Where-Object { $_.State -eq "LISTENING" -and $_.LocalAddress -eq "127.0.0.1" -and $_.LocalPort -eq 6099 } |
            Select-Object -First 1
        if ($listener) {
            $napReady = $true
            break
        }
    }
    if (-not $napReady) {
        throw "NapCat did not start within 45 seconds. Check the NapCat window."
    }
    Write-Host "NapCat started."
}

Write-Host "Nalmai is running. AstrBot dashboard: http://127.0.0.1:6185"
Write-Host "If QQ is offline, sign in from the QQ window opened by NapCat."

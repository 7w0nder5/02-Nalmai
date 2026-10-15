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
$napDir = Join-Path $projectRoot "runtime\NapCat-Shell-4.18.28"
$pidFile = Join-Path $projectRoot "runtime\nalmai-state\astrbot.pid"
$stoppedAnything = $false

if (Test-Path -LiteralPath $pidFile) {
    $astrPidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $astrPidValue = 0
    if ([int]::TryParse($astrPidText, [ref]$astrPidValue)) {
        $astrProcess = Get-Process -Id $astrPidValue -ErrorAction SilentlyContinue
        if ($astrProcess) {
            $ownedPorts = @(Get-LocalTcpRows |
                Where-Object { $_.State -eq "LISTENING" -and $_.OwningProcess -eq $astrPidValue -and $_.LocalPort -in @(6185, 6199) } |
                Select-Object -ExpandProperty LocalPort -Unique)
            $isManagedPython = $astrProcess.Path -eq (Join-Path $astrDir ".venv\Scripts\python.exe")
            if ($isManagedPython -or $ownedPorts.Count -eq 2) {
                Stop-Process -Id $astrPidValue -Force
                Write-Host "AstrBot stopped (PID $astrPidValue)."
                $stoppedAnything = $true
            } else {
                Write-Warning "The saved PID is not Nalmai AstrBot. It was not stopped."
            }
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$napExecutable = Join-Path $napDir "NapCatWinBootMain.exe"
$napProcesses = @(Get-Process -Name "NapCatWinBootMain" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $napExecutable })
foreach ($napProcess in $napProcesses) {
    & "$env:SystemRoot\System32\taskkill.exe" /PID $napProcess.Id /T /F | Out-Null
    Write-Host "NapCat stopped (PID $($napProcess.Id))."
    $stoppedAnything = $true
}

if (-not $stoppedAnything) {
    Write-Host "Nalmai was already stopped."
}

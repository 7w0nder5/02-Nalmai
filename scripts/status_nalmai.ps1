$ErrorActionPreference = "SilentlyContinue"
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

$requiredPorts = @(
    [pscustomobject]@{ Name = "AstrBot dashboard"; Port = 6185 },
    [pscustomobject]@{ Name = "AstrBot OneBot"; Port = 6199 },
    [pscustomobject]@{ Name = "NapCat WebUI"; Port = 6099 }
)

foreach ($service in $requiredPorts) {
    $listener = Get-LocalTcpRows |
        Where-Object { $_.State -eq "LISTENING" -and $_.LocalAddress -eq "127.0.0.1" -and $_.LocalPort -eq $service.Port } |
        Select-Object -First 1
    if ($listener) {
        Write-Host "[OK] $($service.Name) 127.0.0.1:$($service.Port) (PID $($listener.OwningProcess))"
    } else {
        Write-Host "[DOWN] $($service.Name) 127.0.0.1:$($service.Port)"
    }
}

$oneBotConnections = @(Get-LocalTcpRows |
    Where-Object { $_.State -eq "ESTABLISHED" -and ($_.LocalPort -eq 6199 -or $_.RemotePort -eq 6199) })
if ($oneBotConnections.Count -gt 0) {
    Write-Host "[OK] NapCat and AstrBot OneBot WebSocket is connected."
} else {
    Write-Host "[DOWN] OneBot WebSocket is not connected. Check QQ login."
}

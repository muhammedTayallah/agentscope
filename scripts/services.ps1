<#
.SYNOPSIS
  Start/stop/check local Postgres 16 and Redis, which run inside the WSL distro (on E:).

.DESCRIPTION
  Docker can't pull images here (see docs/decisions.md), so local dev uses the services
  installed in WSL by scripts/wsl-setup.sh. WSL stops its VM when no session is open,
  so `start` keeps a hidden session alive; `stop` closes it.

.EXAMPLE
  .\scripts\services.ps1 start
#>
param(
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'start'
)

$Distro = 'Ubuntu-24.04'
$Marker = 'agentscope-keepalive'
$Ports = @{ Postgres = 5432; Redis = 6379 }

function Get-Keepalive {
    Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" |
        Where-Object { $_.CommandLine -like "*$Marker*" }
}

function Test-Port([int]$Port) {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.Connect('127.0.0.1', $Port); return $true } catch { return $false } finally { $c.Close() }
}

switch ($Action) {
    'start' {
        if (-not (Get-Keepalive)) {
            Start-Process -WindowStyle Hidden wsl.exe `
                -ArgumentList "-d $Distro -u root -- bash -c `"service redis-server start >/dev/null; exec -a $Marker sleep infinity`"" | Out-Null
        }
        for ($i = 0; $i -lt 30; $i++) {
            if ((Test-Port $Ports.Postgres) -and (Test-Port $Ports.Redis)) {
                Write-Output 'Postgres (5432) and Redis (6379) are up on 127.0.0.1'
                exit 0
            }
            Start-Sleep -Seconds 1
        }
        Write-Error "Services did not come up within 30s. Check: wsl -d $Distro -u root -- service --status-all"
        exit 1
    }
    'stop' {
        Get-Keepalive | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Write-Output 'Keep-alive stopped (WSL shuts down when idle).'
    }
    'status' {
        $k = if (Get-Keepalive) { 'running' } else { 'not running' }
        $s = $Ports.GetEnumerator() | ForEach-Object {
            "$($_.Key) $($_.Value): $(if (Test-Port $_.Value) { 'open' } else { 'closed' })"
        }
        Write-Output "keep-alive: $k | $($s -join ' | ')"
    }
}

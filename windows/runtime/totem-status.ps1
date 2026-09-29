param([string] $ConfigPath)

$config = Get-Content -Raw $ConfigPath | ConvertFrom-Json

function Test-KioskPort {
    param([int] $Port)
    if ($Port -le 0) { return $false }
    try {
        $client = [Net.Sockets.TcpClient]::new()
        $client.Connect("127.0.0.1", $Port)
        $client.Dispose()
        return $true
    } catch { return $false }
}

function Test-KioskPlayer {
    param([string] $StateDir, [int] $Number)
    if (-not $StateDir) { return $false }
    $path = Join-Path $StateDir "display-$Number.json"
    if (-not (Test-Path $path)) { return $false }
    try {
        $state = Get-Content -Raw $path | ConvertFrom-Json
        return [bool] (Get-Process -Id ([int] $state.pid) -ErrorAction SilentlyContinue)
    } catch { return $false }
}

$stateDir = if ($config.PSObject.Properties.Name -contains "stateDir") { [string] $config.stateDir } else { "" }
$configured = if ($config.PSObject.Properties.Name -contains "screens") { @($config.screens) } else { @() }

$screens = @()
foreach ($screen in $configured) {
    $port = if ($screen.PSObject.Properties.Name -contains "port") { [int] $screen.port } else { 0 }
    $webapp = ($screen.type -eq "webapp") -and (Test-KioskPort $port)
    $running = if ($screen.type -eq "webapp") { $webapp } else { Test-KioskPlayer $stateDir ([int] $screen.number) }
    $screens += [ordered]@{
        number = [int] $screen.number
        totem_type = [string] $screen.type
        kiosk_running = [bool] $running
        webapp_running = [bool] $webapp
    }
}

$webappRunning = Test-KioskPort ([int] $config.port)
$kioskRunning = if ($screens.Count -gt 0) {
    [bool] (@($screens | Where-Object { $_.kiosk_running }).Count -gt 0)
} else {
    [bool] (Get-Process msedge, vlc -ErrorAction SilentlyContinue | Select-Object -First 1)
}

$payload = [ordered]@{
    totem_id = $config.totemId
    totem_type = $config.totemType
    machineName = $env:COMPUTERNAME
    checkedAt = [DateTime]::UtcNow.ToString("o")
    kiosk_running = $kioskRunning
    webapp_running = $webappRunning
    screenCount = $screens.Count
    screens = $screens
} | ConvertTo-Json -Depth 4
Invoke-WebRequest -UseBasicParsing -Method Post -Uri $config.endpointUrl `
    -Headers @{ Authorization = "Bearer $($config.token)" } `
    -ContentType "application/json" -Body $payload | Out-Null

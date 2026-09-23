param([string] $ConfigPath)

$config = Get-Content -Raw $ConfigPath | ConvertFrom-Json
$running = [bool] (Get-Process msedge,vlc -ErrorAction SilentlyContinue | Select-Object -First 1)
$webapp = $false
try {
    $client = [Net.Sockets.TcpClient]::new()
    $client.Connect("127.0.0.1", [int] $config.port)
    $client.Dispose()
    $webapp = $true
} catch {}
$payload = @{
    totem_id = $config.totemId
    totem_type = $config.totemType
    machineName = $env:COMPUTERNAME
    checkedAt = [DateTime]::UtcNow.ToString("o")
    kiosk_running = $running
    webapp_running = $webapp
} | ConvertTo-Json
Invoke-WebRequest -UseBasicParsing -Method Post -Uri $config.endpointUrl `
    -Headers @{ Authorization = "Bearer $($config.token)" } `
    -ContentType "application/json" -Body $payload | Out-Null

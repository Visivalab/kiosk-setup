function Get-SavedRustDesk {
    $path = Join-Path (Get-KioskMachineRoot) "rustdesk.json"
    if (Test-Path $path) {
        Get-Content -Raw $path | ConvertFrom-Json
        return
    }
    [pscustomobject]@{ id = $null; password = $null }
}

function Install-KioskStatusReporter {
    param([string] $Endpoint, [string] $Token, [string] $TotemType)
    $root = Get-KioskMachineRoot
    $configPath = Join-Path $root "totem-status.json"
    $scriptPath = Join-Path $root "totem-status.ps1"
    @{
        endpointUrl = $Endpoint; token = $Token; totemId = $env:COMPUTERNAME; totemType = $TotemType; port = 8080
    } | ConvertTo-Json | Set-Content -Encoding UTF8 $configPath
    Protect-KioskFile $configPath
    Copy-Item (Join-Path $script:WindowsRoot "runtime\totem-status.ps1") $scriptPath -Force
    $taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ConfigPath `"$configPath`""
    $interval = [int] $script:SharedConfig.statusIntervalMinutes
    & schtasks.exe /Create /F /SC MINUTE /MO $interval /TN "pi-kiosk-totem-status" /TR $taskCommand /RU SYSTEM | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not install the status task." }
    & schtasks.exe /Run /TN "pi-kiosk-totem-status" | Out-Null
}

function Get-KioskStatusEndpoint {
    param([string] $RegistrationEndpoint)
    $builder = [UriBuilder]::new([uri] $RegistrationEndpoint)
    $parts = @($builder.Path.TrimEnd("/") -split "/")
    $parts[-1] = "totem-status"
    $builder.Path = $parts -join "/"
    $builder.Query = ""
    $builder.Fragment = ""
    $builder.Uri.AbsoluteUri
}

function Register-KioskTotem {
    param([string] $TotemType)
    if (-not (Read-KioskConfirmation $script:SharedConfig.prompts.registerTotem $true)) {
        Write-KioskDone "skipped totem registration."
        return
    }
    $name = Read-KioskRequired $script:SharedConfig.prompts.totemName
    $description = (Read-Host $script:SharedConfig.prompts.totemDescription).Trim()
    $location = (Read-Host $script:SharedConfig.prompts.totemLocation).Trim()
    $credentials = Get-SavedRustDesk
    $machineId = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Cryptography").MachineGuid
    $endpoint = if ($env:PI_KIOSK_REGISTER_TOTEM_URL) { $env:PI_KIOSK_REGISTER_TOTEM_URL } else { $script:SharedConfig.registerTotemUrl }
    $token = if ($env:PI_KIOSK_REGISTER_TOTEM_TOKEN) { $env:PI_KIOSK_REGISTER_TOTEM_TOKEN } else { $script:SharedConfig.registerTotemToken }
    $payload = @{
        totem_id = $env:COMPUTERNAME; totemType = $TotemType; machineName = $env:COMPUTERNAME;
        machineId = $machineId; name = $name; description = $description; location = $location;
        rustdeskId = $credentials.id; rustdeskPassword = $credentials.password;
        registeredAt = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json
    Write-KioskProgress "Registering totem"
    Invoke-WebRequest -UseBasicParsing -Method Post -Uri $endpoint -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $payload | Out-Null
    $statusEndpoint = Get-KioskStatusEndpoint $endpoint
    Install-KioskStatusReporter $statusEndpoint $token $TotemType
    Write-KioskDone "totem registered for machine $env:COMPUTERNAME. Status reporter installed."
}

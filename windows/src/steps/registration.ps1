function Get-SavedRustDesk {
    $path = Join-Path (Get-KioskMachineRoot) "rustdesk.json"
    if (Test-Path $path) {
        Get-Content -Raw -Encoding UTF8 $path | ConvertFrom-Json
        return
    }
    [pscustomobject]@{ id = $null; password = $null }
}

function ConvertTo-KioskScreenReport {
    param([object[]] $Displays)
    @(@($Displays) | ForEach-Object {
        [ordered]@{
            number     = $_.Number
            deviceName = $_.DeviceName
            type       = $_.Type
            rotation   = $_.Rotation
            source     = $_.Source
            port       = $_.Port
            audio      = [bool] $_.Audio
        }
    })
}

function Install-KioskStatusReporter {
    param([string] $Endpoint, [string] $Token, [object[]] $Displays)

    $root = Get-KioskMachineRoot
    $configPath = Join-Path $root "totem-status.json"
    $scriptPath = Join-Path $root "totem-status.ps1"
    $webPorts = @(@($Displays) | Where-Object { $_.Port -gt 0 } | ForEach-Object { $_.Port })
    $screens = @(@($Displays) | ForEach-Object {
        [ordered]@{ number = $_.Number; type = $_.Type; port = $_.Port }
    })
    $reportedPort = if ($webPorts.Count -gt 0) { $webPorts[0] } else { 8080 }
    [ordered]@{
        endpointUrl = $Endpoint
        token = $Token
        totemId = $env:COMPUTERNAME
        totemType = @($Displays)[0].Type
        port = $reportedPort
        stateDir = Join-Path (Get-KioskRoot) "state"
        screens = $screens
    } | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $configPath
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
    [CmdletBinding()]
    param(
        [string] $TotemType,
        [object[]] $Displays = @(),
        [string] $Name,
        [string] $Description = "",
        [string] $Location = ""
    )
    if (-not $PSBoundParameters.ContainsKey("Name")) {
        if (-not (Read-KioskConfirmation $script:SharedConfig.prompts.registerTotem $true)) {
            Write-KioskDone "skipped totem registration."
            return
        }
        $Name = Read-KioskRequired $script:SharedConfig.prompts.totemName
        $Description = (Read-Host $script:SharedConfig.prompts.totemDescription).Trim()
        $Location = (Read-Host $script:SharedConfig.prompts.totemLocation).Trim()
    } elseif (-not $Name.Trim()) {
        throw "Totem name cannot be empty."
    }
    $credentials = Get-SavedRustDesk
    $machineId = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Cryptography").MachineGuid
    $endpoint = if ($env:PI_KIOSK_REGISTER_TOTEM_URL) { $env:PI_KIOSK_REGISTER_TOTEM_URL } else { $script:SharedConfig.registerTotemUrl }
    $token = if ($env:PI_KIOSK_REGISTER_TOTEM_TOKEN) { $env:PI_KIOSK_REGISTER_TOTEM_TOKEN } else { $script:SharedConfig.registerTotemToken }
    $screens = ConvertTo-KioskScreenReport $Displays
    $payload = [ordered]@{
        totem_id = $env:COMPUTERNAME; totemType = $TotemType; machineName = $env:COMPUTERNAME;
        machineId = $machineId; name = $name; description = $description; location = $location;
        rustdeskId = $credentials.id; rustdeskPassword = $credentials.password;
        screenCount = $screens.Count; screens = $screens;
        registeredAt = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json -Depth 4
    Write-KioskProgress "Registering totem"
    Invoke-WebRequest -UseBasicParsing -Method Post -Uri $endpoint -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $payload | Out-Null
    $statusEndpoint = Get-KioskStatusEndpoint $endpoint
    Install-KioskStatusReporter $statusEndpoint $token $Displays
    Write-KioskDone "totem registered for machine $env:COMPUTERNAME with $($screens.Count) screen(s). Status reporter installed."
}

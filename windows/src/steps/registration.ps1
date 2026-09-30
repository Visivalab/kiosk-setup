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

function Get-KioskJsonValue {
    param([object] $Object, [string] $Name, $Default)

    if (-not $Object) { return $Default }
    if ($Object.PSObject.Properties.Name -notcontains $Name) { return $Default }
    $value = $Object.$Name
    if ($null -eq $value) { return $Default }
    $value
}

function Get-KioskRegistrationDisplays {
    $state = Get-KioskState
    if (-not $state) { return $null }
    $entries = @(Get-KioskJsonValue $state "displays" @())
    if ($entries.Count -eq 0) { return $null }
    @($entries | ForEach-Object {
        [pscustomobject]@{
            Number     = [int] (Get-KioskJsonValue $_ "number" 0)
            DeviceName = [string] (Get-KioskJsonValue $_ "deviceName" "")
            Type       = [string] (Get-KioskJsonValue $_ "type" "video")
            Rotation   = [string] (Get-KioskJsonValue $_ "rotation" "none")
            Source     = [string] (Get-KioskJsonValue $_ "source" "")
            Port       = [int] (Get-KioskJsonValue $_ "port" 0)
            Audio      = [bool] (Get-KioskJsonValue $_ "audio" $false)
        }
    })
}

function Register-KioskTotemNow {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [AllowEmptyString()][string] $Description = "",
        [AllowEmptyString()][string] $Location = "",
        [AllowEmptyString()][string] $TotemType = "",
        [Nullable[bool]] $SkipRustDesk = $null
    )

    $displays = Get-KioskRegistrationDisplays
    if ($displays) {
        Write-KioskDone "reusing the kiosk setup saved on this PC: $($displays.Count) screen(s)."
    } else {
        if (-not $TotemType) {
            throw "This PC has no saved kiosk setup, so the totem type must be given."
        }
        $displays = @(@(Get-KioskDisplays) | ForEach-Object { New-KioskDisplayPlan $_ -Type $TotemType })
        Write-KioskDone "no kiosk setup saved on this PC, so registering $($displays.Count) detected screen(s) as $TotemType."
    }
    $skip = if ($null -ne $SkipRustDesk) { [bool] $SkipRustDesk } else {
        [bool] (Get-KioskJsonValue (Get-KioskState) "skipRustDesk" $false)
    }
    Register-KioskTotem -TotemType $displays[0].Type -Displays $displays `
        -Name $Name -Description $Description -Location $Location -SkipRustDesk:$skip
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
        [string] $Location = "",
        [switch] $SkipRustDesk
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
    $credentials = if ($SkipRustDesk) { [pscustomobject]@{ id = $null; password = $null } } else { Get-SavedRustDesk }
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

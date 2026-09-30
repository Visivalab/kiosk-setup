function Get-KioskSharedConfig {
    $local = Join-Path (Split-Path $script:WindowsRoot -Parent) "shared\kiosk.json"
    if (Test-Path $local) {
        Get-Content -Raw -Encoding UTF8 -Path $local | ConvertFrom-Json
        return
    }
    throw "Shared kiosk configuration was not found at $local."
}

function Test-KioskAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-KioskRoot {
    $path = Join-Path $env:LOCALAPPDATA "pi-kiosk"
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    $path
}

function Get-KioskMachineRoot {
    $path = Join-Path $env:ProgramData "pi-kiosk"
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    $path
}

function Protect-KioskFile {
    param([string] $Path)
    & icacls.exe $Path /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" | Out-Null
}

function Set-KioskStartup {
    param([string] $Launcher)
    $startup = [Environment]::GetFolderPath("Startup")
    $path = Join-Path $startup "pi-kiosk.cmd"
    "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Launcher`"`r`n" |
        Set-Content -Encoding ASCII -Path $path
}

function Get-KioskStatePath {
    Join-Path (Get-KioskMachineRoot) "kiosk-state.json"
}

function Save-KioskState {
    param([object] $Plan, [string] $Launcher)

    $displays = @(@($Plan.Displays) | ForEach-Object {
        [ordered]@{
            number     = $_.Number
            deviceName = $_.DeviceName
            monitorId  = $_.MonitorId
            rotation   = $_.Rotation
            type       = $_.Type
            source     = $_.Source
            path       = $_.Path
            port       = $_.Port
            audio      = [bool] $_.Audio
        }
    })
    $state = [ordered]@{
        version   = 1
        updatedAt = [DateTime]::UtcNow.ToString("o")
        launcher  = $Launcher
        stateDir  = Join-Path (Get-KioskRoot) "state"
        audioDisplay = $Plan.AudioDisplay
        audioDevice = $Plan.AudioDevice
        audioDeviceName = $Plan.AudioDeviceName
        skipRustDesk = $Plan.SkipRustDesk
        ports     = @(@($Plan.Displays) | Where-Object { $_.Port -gt 0 } | ForEach-Object { $_.Port })
        displays  = $displays
    }
    $path = Get-KioskStatePath
    $state | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -Path $path
    Protect-KioskFile $path
    $path
}

function Get-KioskState {
    $path = Join-Path $env:ProgramData "pi-kiosk\kiosk-state.json"
    if (-not (Test-Path $path)) { return $null }
    try { Get-Content -Raw -Encoding UTF8 -Path $path | ConvertFrom-Json } catch { $null }
}

function Get-KioskSharedConfig {
    $local = Join-Path (Split-Path $script:WindowsRoot -Parent) "shared\kiosk.json"
    if (Test-Path $local) {
        Get-Content -Raw -Path $local | ConvertFrom-Json
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

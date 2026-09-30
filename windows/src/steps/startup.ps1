function Get-KioskStateDir {
    $path = Join-Path (Get-KioskRoot) "state"
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    $path
}

function Write-KioskOrchestrator {
    param([object[]] $Displays, [AllowEmptyString()][string] $AudioDevice = "")

    $root = Get-KioskRoot
    $bin = Join-Path $root "bin"
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $stateDir = Get-KioskStateDir
    Remove-Item (Join-Path $stateDir "display-*.json") -Force -ErrorAction SilentlyContinue

    $items = @(@($Displays) | ForEach-Object {
        [ordered]@{
            number   = $_.Number
            device   = $_.DeviceName
            monitorId = $_.MonitorId
            type     = $_.Type
            path     = $_.Path
            launcher = $_.Launcher
            audio    = [bool] $_.Audio
        }
    })
    $json = (ConvertTo-Json @($items) -Depth 4 -Compress).Replace("'", "''")
    $vlc = if (@($Displays) | Where-Object { $_.Type -eq "video" }) { [string] (Find-Vlc) } else { "" }

    $header = @(
        '$ErrorActionPreference = "Stop"',
        ("`$items = @((ConvertFrom-Json '{0}') | ForEach-Object {{ `$_ }})" -f $json),
        ("`$vlc = '{0}'" -f $vlc.Replace("'", "''")),
        ("`$stateDir = '{0}'" -f $stateDir.Replace("'", "''")),
        ("`$audioDevice = '{0}'" -f $AudioDevice.Replace("'", "''")),
        ""
    ) -join "`r`n"

    $body = @'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class KioskMonitorIdentity {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DISPLAY_DEVICE {
        public int cb;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString;
        public int StateFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey;
    }
    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "EnumDisplayDevicesW")]
    static extern bool EnumDisplayDevices(string deviceName, int index, ref DISPLAY_DEVICE device, int flags);
    public static string GetId(string deviceName) {
        var device = new DISPLAY_DEVICE();
        device.cb = Marshal.SizeOf(typeof(DISPLAY_DEVICE));
        if (!EnumDisplayDevices(deviceName, 0, ref device, 1)) return "";
        return device.DeviceID ?? "";
    }
}
"@
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Get-KioskMonitorId {
    param([string] $DeviceName)
    [KioskMonitorIdentity]::GetId($DeviceName)
}

function Get-KioskScreenNumber {
    param([string] $DeviceName, [string] $MonitorId, [object[]] $Screens = @([System.Windows.Forms.Screen]::AllScreens))
    $matches = @()
    for ($index = 0; $index -lt $Screens.Count; $index++) {
        if ($MonitorId) {
            if ((Get-KioskMonitorId $Screens[$index].DeviceName) -eq $MonitorId) { $matches += $index }
        } elseif ($Screens[$index].DeviceName -eq $DeviceName) {
            # Legacy launcher: reconfigure to save physical monitor identities.
            $matches += $index
        }
    }
    if ($matches.Count -eq 1) { return $matches[0] }
    throw "Configured monitor $MonitorId ($DeviceName) is missing or ambiguous. Refusing to play on another screen."
}

function Test-KioskAudioDevice {
    param([string] $Id)

    if (-not $Id) { return $false }
    $guid = $Id.Substring($Id.LastIndexOf(".") + 1)
    $path = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render\$guid"
    if (-not (Test-Path $path)) { return $false }
    $state = Get-ItemProperty -Path $path -Name DeviceState -ErrorAction SilentlyContinue
    if (-not $state) { return $false }
    $state.DeviceState -eq 1
}

function Start-KioskPlayer {
    param([object] $Item)

    if ($Item.type -eq "webapp") {
        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $Item.launcher
        return Start-Process powershell.exe -ArgumentList $arguments -PassThru
    }
    $arguments = @(
        "--no-one-instance", "--fullscreen", "--repeat", "--no-video-title-show", "--no-qt-fs-controller", "--mouse-hide-timeout=0",
        ("--qt-fullscreen-screennumber={0}" -f (Get-KioskScreenNumber -DeviceName $Item.device -MonitorId $Item.monitorId))
    )
    if ($Item.audio) {
        if (Test-KioskAudioDevice $audioDevice) {
            $arguments += @("--aout=mmdevice", ("--mmdevice-audio-device={0}" -f $audioDevice))
        }
    } else {
        $arguments += "--no-audio"
    }
    # Start-Process joins ArgumentList with spaces; quote the path for Windows command-line parsing.
    $arguments += ('"{0}"' -f $Item.path)
    Start-Process -FilePath $vlc -ArgumentList $arguments -PassThru
}

function Save-KioskPlayerState {
    param([object] $Item, [object] $Process)
    @{ pid = $Process.Id; type = $Item.type; number = $Item.number } | ConvertTo-Json |
        Set-Content -Encoding UTF8 (Join-Path $stateDir ("display-{0}.json" -f $Item.number))
}

$failureLog = Join-Path $stateDir "kiosk-start-error.log"
Remove-Item $failureLog -Force -ErrorAction SilentlyContinue
try {
$started = @()
foreach ($item in $items) {
    $process = Start-KioskPlayer $item
    Save-KioskPlayerState $item $process
    $started += [pscustomobject]@{ Item = $item; Process = $process }
}

$ids = @($started | ForEach-Object { $_.Process.Id })
if ($ids.Count -gt 0) { Wait-Process -Id $ids }
} catch {
    $details = $_ | Format-List * -Force | Out-String
    $details | Set-Content -Encoding UTF8 $failureLog
    [Console]::Error.WriteLine("Kiosk launcher failed. See $failureLog`r`n$details")
    exit 1
}
'@

    $launcher = Join-Path $bin "kiosk-start.ps1"
    Set-Content -Encoding UTF8 -Path $launcher -Value ($header + $body)
    $launcher
}

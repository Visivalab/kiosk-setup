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
            type     = $_.Type
            path     = $_.Path
            launcher = $_.Launcher
            rcPort   = 9010 + $_.Number
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
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Get-KioskScreenNumber {
    param([string] $DeviceName)
    $screens = @([System.Windows.Forms.Screen]::AllScreens)
    for ($index = 0; $index -lt $screens.Count; $index++) {
        if ($screens[$index].DeviceName -eq $DeviceName) { return $index }
    }
    throw "Configured display $DeviceName is no longer part of the extended desktop. Check Windows display settings."
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
    param([object] $Item, [bool] $Paused)

    if ($Item.type -eq "webapp") {
        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $Item.launcher
        return Start-Process powershell.exe -ArgumentList $arguments -PassThru
    }
    $arguments = @(
        "--no-one-instance", "--fullscreen", "--loop", "--no-video-title-show", "--no-qt-fs-controller", "--mouse-hide-timeout=0",
        ("--qt-fullscreen-screennumber={0}" -f (Get-KioskScreenNumber $Item.device))
    )
    if ($Item.audio) {
        if (Test-KioskAudioDevice $audioDevice) {
            $arguments += @("--aout=mmdevice", ("--mmdevice-audio-device={0}" -f $audioDevice))
        }
    } else {
        $arguments += "--no-audio"
    }
    if ($Paused) {
        $arguments += @("--start-paused", "--extraintf", "rc", "--rc-host", ("127.0.0.1:{0}" -f $Item.rcPort))
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

function Connect-KioskPlayers {
    param([object[]] $Items, [int] $TimeoutSeconds = 30)

    $clients = @()
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    foreach ($item in $Items) {
        $client = $null
        while (-not $client -and (Get-Date) -lt $deadline) {
            try {
                $candidate = [Net.Sockets.TcpClient]::new()
                $candidate.Connect("127.0.0.1", [int] $item.rcPort)
                $client = $candidate
            } catch {
                Start-Sleep -Milliseconds 200
            }
        }
        if (-not $client) {
            foreach ($open in $clients) { $open.Dispose() }
            return @()
        }
        $clients += $client
    }
    $clients
}

$failureLog = Join-Path $stateDir "kiosk-start-error.log"
Remove-Item $failureLog -Force -ErrorAction SilentlyContinue
try {
$videos = @($items | Where-Object { $_.type -eq "video" })
$synchronised = $videos.Count -gt 1
$started = @()
foreach ($item in $items) {
    $process = Start-KioskPlayer $item $synchronised
    Save-KioskPlayerState $item $process
    $started += [pscustomobject]@{ Item = $item; Process = $process }
}

if ($synchronised) {
    $clients = @(Connect-KioskPlayers $videos)
    if ($clients.Count -eq $videos.Count) {
        $release = [Text.Encoding]::ASCII.GetBytes("play`r`n")
        foreach ($client in $clients) { $client.GetStream().Write($release, 0, $release.Length) }
        foreach ($client in $clients) { $client.GetStream().Flush(); $client.Dispose() }
    } else {
        foreach ($entry in $started) {
            if ($entry.Item.type -eq "video") { Stop-Process -Id $entry.Process.Id -Force -ErrorAction SilentlyContinue }
        }
        $started = @($started | Where-Object { $_.Item.type -ne "video" })
        foreach ($item in $videos) {
            $process = Start-KioskPlayer $item $false
            Save-KioskPlayerState $item $process
            $started += [pscustomobject]@{ Item = $item; Process = $process }
        }
    }
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

$script:KioskRenderRoot = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
$script:KioskRenderPrefix = "{0.0.0.00000000}."

function Get-KioskRegistryValue {
    param([string] $Path, [string] $Name)

    $item = Get-ItemProperty -Path $Path -Name $Name -ErrorAction SilentlyContinue
    if (-not $item) { return $null }
    $item.$Name
}

function Get-KioskAudioDevices {
    [CmdletBinding()]
    param([string] $Root = $script:KioskRenderRoot)

    if (-not (Test-Path $Root)) { return @() }
    $nameKeys = @(
        "{b3f8fa53-0004-438e-9003-51a46e139bf8},6",
        "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
    )
    @(Get-ChildItem -Path $Root -ErrorAction SilentlyContinue | ForEach-Object {
        if ((Get-KioskRegistryValue $_.PSPath "DeviceState") -ne 1) { return }
        $name = ""
        foreach ($key in $nameKeys) {
            $value = Get-KioskRegistryValue (Join-Path $_.PSPath "Properties") $key
            if ($value) { $name = [string] $value; break }
        }
        if (-not $name) { $name = $_.PSChildName }
        [pscustomobject]@{ Id = $script:KioskRenderPrefix + $_.PSChildName; Name = $name }
    } | Sort-Object Name)
}

function Test-KioskVideoHasAudio {
    param([string] $Path)

    if (-not $Path -or -not (Test-Path $Path)) { return $true }
    try {
        $shell = New-Object -ComObject Shell.Application
        $folder = $shell.Namespace([IO.Path]::GetDirectoryName($Path))
        if (-not $folder) { return $true }
        $item = $folder.ParseName([IO.Path]::GetFileName($Path))
        if (-not $item) { return $true }
        foreach ($property in @("System.Audio.ChannelCount", "System.Audio.EncodingBitrate", "System.Audio.SampleRate")) {
            if ($item.ExtendedProperty($property)) { return $true }
        }
        return $false
    } catch {
        return $true
    }
}

function Resolve-KioskAudioPlan {
    param([Parameter(Mandatory = $true)][object] $Plan)

    foreach ($display in @($Plan.Displays)) { $display.Audio = $false }
    $videos = @(@($Plan.Displays) | Where-Object { $_.Type -eq "video" })
    if ($videos.Count -eq 0) {
        $Plan.AudioDisplay = 0
        Write-KioskDone "audio follows the webapp and the output available when it plays."
        return
    }

    $requested = [int] $Plan.AudioDisplay
    $carrying = @($videos | Where-Object { Test-KioskVideoHasAudio $_.Path })
    if ($carrying.Count -eq 0) {
        $Plan.AudioDisplay = 0
        Write-KioskDone "no video carries an audio track, so every screen plays muted."
        return
    }

    $selected = @($carrying | Where-Object { $_.Number -eq $requested })
    $display = if ($selected.Count -eq 1) { $selected[0] } else { $carrying[0] }
    $display.Audio = $true
    $Plan.AudioDisplay = $display.Number

    $output = if ($Plan.AudioDeviceName) { $Plan.AudioDeviceName } else { "the output available when it plays" }
    if ($videos.Count -eq 1) {
        Write-KioskDone "audio plays from the video on display $($display.Number) through $output."
    } elseif ($requested -eq $display.Number) {
        Write-KioskDone "audio plays from display $($display.Number) through $output. The other screens are muted."
    } else {
        Write-KioskDone "display $requested has no audio track, so audio plays from display $($display.Number) through $output. The other screens are muted."
    }
}

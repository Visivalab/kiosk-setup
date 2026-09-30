$script:KioskRotations = @("none", "clockwise", "counterclockwise")
$script:KioskProjectTypes = @("webapp", "video")
$script:KioskFinalActions = @("launch", "reboot", "nothing")
$script:KioskWebAppPort = 8080

function New-KioskDisplayPlan {
    param(
        [Parameter(Mandatory = $true)][object] $Display,
        [string] $Rotation = "none",
        [string] $Type = "video",
        [AllowEmptyString()][string] $Source = ""
    )

    [pscustomobject]@{
        Number     = [int] $Display.Number
        Index      = [int] $Display.Index
        DeviceName = [string] $Display.DeviceName
        MonitorId  = [string] $Display.MonitorId
        Primary    = [bool] $Display.Primary
        Width      = [int] $Display.Width
        Height     = [int] $Display.Height
        Rotation   = $Rotation
        Type       = $Type
        Source     = $Source
        Url        = ""
        Path       = ""
        Launcher   = ""
        Port       = 0
        Audio      = $false
    }
}

function New-KioskPlan {
    param(
        [object[]] $Displays = @(),
        [AllowEmptyString()][string] $WindowsPassword = "",
        [AllowEmptyString()][string] $RustDeskPassword = "",
        [bool] $SkipRustDesk = $false,
        [bool] $Register = $false,
        [AllowEmptyString()][string] $TotemName = "",
        [AllowEmptyString()][string] $TotemDescription = "",
        [AllowEmptyString()][string] $TotemLocation = "",
        [string] $FinalAction = "nothing",
        [int] $AudioDisplay = 0,
        [AllowEmptyString()][string] $AudioDevice = "",
        [AllowEmptyString()][string] $AudioDeviceName = ""
    )

    [pscustomobject]@{
        Displays         = @($Displays)
        WindowsPassword  = $WindowsPassword
        RustDeskPassword = if ($SkipRustDesk) { "" } else { $RustDeskPassword }
        SkipRustDesk     = $SkipRustDesk
        Register         = $Register
        TotemName        = $TotemName
        TotemDescription = $TotemDescription
        TotemLocation    = $TotemLocation
        FinalAction      = $FinalAction
        AudioDisplay     = $AudioDisplay
        AudioDevice      = $AudioDevice
        AudioDeviceName  = $AudioDeviceName
    }
}

function Test-KioskPlan {
    param([Parameter(Mandatory = $true)][object] $Plan)

    $displays = @($Plan.Displays)
    if ($displays.Count -eq 0) { return "No active displays were detected." }
    if ($displays.Count -gt 1) {
        $ids = @($displays | ForEach-Object { $_.MonitorId })
        if (@($ids | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -gt 0 -or
            @($ids | Select-Object -Unique).Count -ne $displays.Count) {
            return "Windows could not uniquely identify every physical monitor. Nothing was changed."
        }
    }
    if (-not $Plan.SkipRustDesk -and [string]::IsNullOrWhiteSpace($Plan.RustDeskPassword)) { return "Enter a RustDesk password." }
    if ($Plan.FinalAction -notin $script:KioskFinalActions) { return "Choose what to do after setup." }

    foreach ($display in $displays) {
        $label = "Display $($display.Number)"
        if ($display.Rotation -notin $script:KioskRotations) { return "$label needs a screen rotation." }
        if ($display.Type -notin $script:KioskProjectTypes) { return "$label needs a kiosk type." }
        if ($displays.Count -gt 1 -and $display.Type -ne "video") {
            return "Multiple displays can only run video kiosks. $label is set to webapp."
        }
        try {
            if ($display.Type -eq "webapp") { [void] (Normalize-WebAppSource $display.Source) }
            else {
                $videoSource = Normalize-VideoSource $display.Source
                if (Test-KioskLocalVideoSource $videoSource) {
                    if (-not (Test-Path -LiteralPath $videoSource -PathType Leaf)) {
                        return "$label - local video file not found: $videoSource"
                    }
                    if ((Get-Item -LiteralPath $videoSource).Length -eq 0) {
                        return "$label - local video file is empty: $videoSource"
                    }
                }
            }
        } catch {
            return "$label - $($_.Exception.Message)"
        }
    }

    if ($Plan.AudioDisplay -ne 0) {
        $source = @($displays | Where-Object { $_.Number -eq $Plan.AudioDisplay })
        if ($source.Count -ne 1 -or $source[0].Type -ne "video") {
            return "Choose which video the audio comes from."
        }
    }

    if ($Plan.Register -and [string]::IsNullOrWhiteSpace($Plan.TotemName)) {
        return "Enter a totem name or turn off registration."
    }
    $null
}

function Resolve-KioskPlan {
    param([Parameter(Mandatory = $true)][object] $Plan)

    $port = $script:KioskWebAppPort
    foreach ($display in @($Plan.Displays)) {
        if ($display.Type -eq "webapp") {
            $display.Url = Normalize-WebAppSource $display.Source
            $display.Port = $port
            $port++
        } else {
            $display.Url = Normalize-VideoSource $display.Source
        }
    }
    $Plan
}

function Get-KioskPlanTotemType {
    param([object] $Plan)
    @($Plan.Displays)[0].Type
}

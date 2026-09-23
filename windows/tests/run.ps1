Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "..\kiosk.ps1")

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)] $Expected,
        [Parameter(Mandatory = $true)] $Actual,
        [Parameter(Mandatory = $true)] [string] $Message
    )

    if ($Expected -ne $Actual) {
        throw "$Message Expected '$Expected', got '$Actual'."
    }
}

$fakeScreens = @(
    [pscustomobject]@{
        DeviceName = "right"
        Primary = $false
        Bounds = [pscustomobject]@{ X = 1920; Y = 0; Width = 1280; Height = 1024 }
    },
    [pscustomobject]@{
        DeviceName = "primary"
        Primary = $true
        Bounds = [pscustomobject]@{ X = 0; Y = 0; Width = 1920; Height = 1080 }
    },
    [pscustomobject]@{
        DeviceName = "left"
        Primary = $false
        Bounds = [pscustomobject]@{ X = -1280; Y = 0; Width = 1280; Height = 1024 }
    }
)

$displays = @(Get-KioskDisplays -Screens $fakeScreens)
Assert-Equal 3 $displays.Count "All active displays should be returned."
Assert-Equal "primary" $displays[0].DeviceName "The primary display should be listed first."
Assert-Equal "left" $displays[1].DeviceName "Other displays should be ordered by position."
Assert-Equal "right" $displays[2].DeviceName "Other displays should be ordered by position."
Assert-Equal 1 $displays[0].Number "Display numbering should start at one."
Assert-Equal 3 $displays[2].Number "Every display should receive a number."
Assert-Equal `
    "1) primary - 1920x1080 at (0,0) - Primary" `
    (Format-KioskDisplay $displays[0]) `
    "Display details should be readable."

Write-Host "Windows display detection tests passed."

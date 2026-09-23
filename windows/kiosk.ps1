Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-KioskDisplays {
    [CmdletBinding()]
    param(
        [AllowEmptyCollection()]
        [object[]] $Screens
    )

    if (-not $PSBoundParameters.ContainsKey("Screens")) {
        if ($env:OS -ne "Windows_NT") {
            throw "This tool only detects displays on Windows. Nothing was changed."
        }
        Add-Type -AssemblyName System.Windows.Forms
        $Screens = [System.Windows.Forms.Screen]::AllScreens
    }

    $ordered = @($Screens) | Sort-Object `
        @{ Expression = { if ($_.Primary) { 0 } else { 1 } } }, `
        @{ Expression = { $_.Bounds.X } }, `
        @{ Expression = { $_.Bounds.Y } }

    $number = 0
    @($ordered | ForEach-Object {
        $number++
        [pscustomobject]@{
            Number     = $number
            DeviceName = [string] $_.DeviceName
            Primary    = [bool] $_.Primary
            X          = [int] $_.Bounds.X
            Y          = [int] $_.Bounds.Y
            Width      = [int] $_.Bounds.Width
            Height     = [int] $_.Bounds.Height
        }
    })
}

function Format-KioskDisplay {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Display
    )

    $primary = if ($Display.Primary) { " - Primary" } else { "" }
    "{0}) {1} - {2}x{3} at ({4},{5}){6}" -f `
        $Display.Number,
        $Display.DeviceName,
        $Display.Width,
        $Display.Height,
        $Display.X,
        $Display.Y,
        $primary
}

function Invoke-KioskMain {
    try {
        $displays = @(Get-KioskDisplays)
        if ($displays.Count -eq 0) {
            throw "No active displays were detected."
        }

        Write-Host "Detected displays"
        Write-Host ""
        foreach ($display in $displays) {
            Write-Host (Format-KioskDisplay $display)
        }
        Write-Host ""
        Write-Host ("Detected {0} active display(s)." -f $displays.Count)
        return 0
    }
    catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        return 1
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    exit (Invoke-KioskMain)
}

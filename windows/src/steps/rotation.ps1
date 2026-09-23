function Get-KioskDisplays {
    [CmdletBinding()]
    param(
        [AllowEmptyCollection()]
        [object[]] $Screens
    )

    if (-not $PSBoundParameters.ContainsKey("Screens")) {
        if ($env:OS -ne "Windows_NT") {
            throw "This tool only configures Windows. Nothing was changed."
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
    param([Parameter(Mandatory = $true)][object] $Display)

    $primary = if ($Display.Primary) { " - Primary" } else { "" }
    "{0}) {1} - {2}x{3} at ({4},{5}){6}" -f `
        $Display.Number, $Display.DeviceName, $Display.Width, $Display.Height,
        $Display.X, $Display.Y, $primary
}

function Initialize-RotationApi {
    if ("KioskDisplay" -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class KioskDisplay {
    [StructLayout(LayoutKind.Sequential)]
    public struct POINTL { public int x; public int y; }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
        public short dmSpecVersion;
        public short dmDriverVersion;
        public short dmSize;
        public short dmDriverExtra;
        public int dmFields;
        public POINTL dmPosition;
        public int dmDisplayOrientation;
        public int dmDisplayFixedOutput;
        public short dmColor;
        public short dmDuplex;
        public short dmYResolution;
        public short dmTTOption;
        public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
        public short dmLogPixels;
        public int dmBitsPerPel;
        public int dmPelsWidth;
        public int dmPelsHeight;
        public int dmDisplayFlags;
        public int dmDisplayFrequency;
        public int dmICMMethod;
        public int dmICMIntent;
        public int dmMediaType;
        public int dmDitherType;
        public int dmReserved1;
        public int dmReserved2;
        public int dmPanningWidth;
        public int dmPanningHeight;
    }

    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    static extern bool EnumDisplaySettings(string deviceName, int modeNum, ref DEVMODE devMode);

    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    static extern int ChangeDisplaySettingsEx(string deviceName, ref DEVMODE devMode, IntPtr hwnd, int flags, IntPtr param);

    public static void Rotate(string deviceName, int orientation) {
        const int ENUM_CURRENT_SETTINGS = -1;
        const int CDS_UPDATEREGISTRY = 1;
        const int DM_DISPLAYORIENTATION = 0x80;
        const int DM_PELSWIDTH = 0x80000;
        const int DM_PELSHEIGHT = 0x100000;
        var mode = new DEVMODE();
        mode.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
        if (!EnumDisplaySettings(deviceName, ENUM_CURRENT_SETTINGS, ref mode))
            throw new InvalidOperationException("Could not read display settings for " + deviceName + ".");
        if ((mode.dmDisplayOrientation % 2) != (orientation % 2)) {
            int width = mode.dmPelsWidth;
            mode.dmPelsWidth = mode.dmPelsHeight;
            mode.dmPelsHeight = width;
        }
        mode.dmDisplayOrientation = orientation;
        mode.dmFields = DM_DISPLAYORIENTATION | DM_PELSWIDTH | DM_PELSHEIGHT;
        int result = ChangeDisplaySettingsEx(deviceName, ref mode, IntPtr.Zero, CDS_UPDATEREGISTRY, IntPtr.Zero);
        if (result != 0)
            throw new InvalidOperationException("Windows rejected the display rotation (code " + result + ").");
    }
}
'@
}

function Set-KioskRotation {
    param([object] $Display, [string] $Rotation)
    Initialize-RotationApi
    $orientation = @{ none = 0; clockwise = 1; counterclockwise = 3 }[$Rotation]
    [KioskDisplay]::Rotate($Display.DeviceName, $orientation)
    $label = @{ none = "no rotation"; clockwise = "clockwise"; counterclockwise = "counterclockwise" }[$Rotation]
    Write-KioskDone "screen rotation set to $label on $($Display.DeviceName) and applied live."
}

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

function Assert-Throws {
    param([scriptblock] $Action, [string] $Message)
    try { & $Action } catch { return }
    throw $Message
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

$script:SharedConfig = [pscustomobject]@{
    s3ReleaseBaseUrl = "https://releases.example/"
    webappPathExample = "screen/app.zip"
}
Assert-Equal `
    "https://releases.example/screen/app.zip" `
    (Normalize-WebAppSource " screen/app.zip ") `
    "The shared S3 base URL should be used."
Assert-Throws `
    { Normalize-WebAppSource "https://example.test/app.zip" } `
    "Full webapp URLs should be rejected."
$video = Normalize-VideoSource "https://www.dropbox.com/s/demo/video.mp4?dl=0"
Assert-Equal "dl=1" ([uri] $video).Query.TrimStart("?") "Dropbox links should request a direct download."
Assert-Throws `
    { Normalize-VideoSource "https://example.test/video.mp4" } `
    "Non-Dropbox video URLs should be rejected."
Assert-Equal `
    "https://example.test/api/totem-status" `
    (Get-KioskStatusEndpoint "https://example.test/api/register-totem?old=1") `
    "Status reporting should replace the final registration path."

Initialize-RotationApi
Assert-Equal 156 ([Runtime.InteropServices.Marshal]::SizeOf([type] [KioskDisplay+DEVMODE])) "The Windows display structure should have the native size."

$runtimeRoot = Join-Path ([IO.Path]::GetTempPath()) ("pi kiosk runtime " + [guid]::NewGuid())
$machineRoot = Join-Path $runtimeRoot "machine"
New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot "app"), $machineRoot | Out-Null
function Find-Edge { "C:\Program Files\Microsoft\Edge\Application\msedge.exe" }
function Get-KioskMachineRoot { $machineRoot }
try {
    $launcher = Write-WebRuntime $runtimeRoot (Join-Path $runtimeRoot "app")
    foreach ($file in @(
        $launcher,
        (Join-Path $runtimeRoot "bin\webapp-server.ps1"),
        (Join-Path $runtimeRoot "bin\cursor-idle.ps1")
    )) {
        $tokens = $null
        $errors = $null
        [void] [Management.Automation.Language.Parser]::ParseFile($file, [ref] $tokens, [ref] $errors)
        Assert-Equal 0 $errors.Count "Generated runtime script $file should parse."
    }
} finally {
    Remove-Item -Recurse -Force $runtimeRoot -ErrorAction SilentlyContinue
}

Write-Host "Windows kiosk tests passed."

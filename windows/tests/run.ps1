Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "..\kiosk.ps1")
. (Join-Path $PSScriptRoot "..\kiosk-gui.ps1")

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)] [AllowNull()] $Expected,
        [Parameter(Mandatory = $true)] [AllowNull()] $Actual,
        [Parameter(Mandatory = $true)] [string] $Message
    )

    if ($Expected -ne $Actual) {
        throw "$Message Expected '$Expected', got '$Actual'."
    }
}

function Assert-Match {
    param([string] $Pattern, [string] $Actual, [string] $Message)
    if ($Actual -notmatch $Pattern) { throw "$Message Expected a match for '$Pattern', got '$Actual'." }
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
Assert-Equal 1 $displays[0].Index "The primary display keeps its Windows enumeration index."
Assert-Equal 2 $displays[1].Index "Every display keeps its Windows enumeration index."
Assert-Equal 0 $displays[2].Index "Every display keeps its Windows enumeration index."
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
$sclVideo = Normalize-VideoSource "https://www.dropbox.com/scl/fi/abc/video.mp4?rlkey=key&st=token&dl=0"
Assert-Match "rlkey=key&st=token&dl=1" $sclVideo "SCL shared links should preserve their access parameters."
Assert-KioskVideoContentType "application/binary"
Assert-KioskVideoContentType "video/mp4"
Assert-KioskVideoContentType "application/binary; charset=utf-8"
Assert-Throws { Assert-KioskVideoContentType "application/binary-malformed" } "Other MIME types should not match the generic binary exception."
Assert-Throws { Assert-KioskVideoContentType "text/html" } "Dropbox HTML pages should be rejected."
Assert-Throws { Assert-KioskVideoContentType "application/json" } "Dropbox JSON responses should be rejected."
Assert-Throws `
    { Normalize-VideoSource "https://example.test/video.mp4" } `
    "Non-Dropbox video URLs should be rejected."
Assert-Equal `
    "https://example.test/api/totem-status" `
    (Get-KioskStatusEndpoint "https://example.test/api/register-totem?old=1") `
    "Status reporting should replace the final registration path."

$dropboxOne = "https://www.dropbox.com/s/one/one.mp4?dl=0"
$dropboxTwo = "https://www.dropbox.com/s/two/two.mp4?dl=0"

function New-TestPlan {
    param([object[]] $PlannedDisplays)
    New-KioskPlan -Displays $PlannedDisplays -RustDeskPassword "remote-secret" `
        -Register $true -TotemName "Lobby" -FinalAction "launch"
}

$singleWebapp = New-TestPlan @(
    (New-KioskDisplayPlan $displays[0] -Rotation "none" -Type "webapp" -Source "screen/app.zip")
)
Assert-Equal $null (Test-KioskPlan $singleWebapp) "A single webapp display should pass validation."
[void] (Resolve-KioskPlan $singleWebapp)
Assert-Equal 8080 $singleWebapp.Displays[0].Port "The only webapp should keep the default port."
Assert-Equal "https://releases.example/screen/app.zip" $singleWebapp.Displays[0].Url "Webapp sources should be normalised."
Assert-Equal "webapp" (Get-KioskPlanTotemType $singleWebapp) "The totem type comes from the first display."

$twoVideos = New-TestPlan @(
    (New-KioskDisplayPlan $displays[0] -Rotation "clockwise" -Type "video" -Source $dropboxOne),
    (New-KioskDisplayPlan $displays[1] -Rotation "counterclockwise" -Type "video" -Source $dropboxTwo)
)
Assert-Equal $null (Test-KioskPlan $twoVideos) "Two video displays should pass validation."
[void] (Resolve-KioskPlan $twoVideos)
Assert-Equal 0 $twoVideos.Displays[0].Port "Video displays should not reserve a port."
Assert-Match "dl=1" $twoVideos.Displays[1].Url "Video sources should be normalised."

$mixed = New-TestPlan @(
    (New-KioskDisplayPlan $displays[0] -Rotation "none" -Type "video" -Source $dropboxOne),
    (New-KioskDisplayPlan $displays[1] -Rotation "none" -Type "webapp" -Source "screen/app.zip")
)
Assert-Match "only run video" (Test-KioskPlan $mixed) "Webapps should be rejected on multi-display setups."

$missingSource = New-TestPlan @(
    (New-KioskDisplayPlan $displays[0] -Rotation "none" -Type "video" -Source ""),
    (New-KioskDisplayPlan $displays[1] -Rotation "none" -Type "video" -Source $dropboxTwo)
)
Assert-Match "Display 1" (Test-KioskPlan $missingSource) "Validation should name the display that is missing a source."

$noPassword = New-TestPlan @(
    (New-KioskDisplayPlan $displays[0] -Rotation "none" -Type "video" -Source $dropboxOne)
)
$noPassword.RustDeskPassword = ""
Assert-Equal "Enter a RustDesk password." (Test-KioskPlan $noPassword) "A RustDesk password should be required."

$unnamed = New-TestPlan @(
    (New-KioskDisplayPlan $displays[0] -Rotation "none" -Type "video" -Source $dropboxOne)
)
$unnamed.TotemName = ""
Assert-Match "totem name" (Test-KioskPlan $unnamed) "Registration should require a totem name."

$badAudio = New-TestPlan @(
    (New-KioskDisplayPlan $displays[0] -Rotation "none" -Type "video" -Source $dropboxOne),
    (New-KioskDisplayPlan $displays[1] -Rotation "none" -Type "video" -Source $dropboxTwo)
)
$badAudio.AudioDisplay = 7
Assert-Match "audio comes from" (Test-KioskPlan $badAudio) "The audio source must be one of the configured videos."
$badAudio.AudioDisplay = 2
Assert-Equal $null (Test-KioskPlan $badAudio) "A video display is a valid audio source."
$badAudio.AudioDisplay = 0
Assert-Equal $null (Test-KioskPlan $badAudio) "Muting every screen is allowed."

$audioRoot = "HKCU:\Software\pi-kiosk-test-$([guid]::NewGuid())"
try {
    $endpoint = "{11111111-2222-3333-4444-555555555555}"
    [void] (New-Item -Path "$audioRoot\$endpoint\Properties" -Force)
    Set-ItemProperty -Path "$audioRoot\$endpoint" -Name DeviceState -Value 1 -Type DWord
    Set-ItemProperty -Path "$audioRoot\$endpoint\Properties" `
        -Name "{b3f8fa53-0004-438e-9003-51a46e139bf8},6" -Value "Speakers (Test)"
    $offline = "{99999999-2222-3333-4444-555555555555}"
    [void] (New-Item -Path "$audioRoot\$offline" -Force)
    Set-ItemProperty -Path "$audioRoot\$offline" -Name DeviceState -Value 8 -Type DWord

    $devices = @(Get-KioskAudioDevices -Root $audioRoot)
    Assert-Equal 1 $devices.Count "Only active render endpoints should be offered."
    Assert-Equal "Speakers (Test)" $devices[0].Name "Endpoints should be listed by their friendly name."
    Assert-Equal "{0.0.0.00000000}.$endpoint" $devices[0].Id "Endpoint ids should carry the render prefix."
} finally {
    Remove-Item -Recurse -Force $audioRoot -ErrorAction SilentlyContinue
}

$savedState = [pscustomobject]@{
    displays = @(
        [pscustomobject]@{ number = 1; deviceName = "primary"; type = "video"; rotation = "clockwise"; source = "a"; port = 0; audio = $true },
        [pscustomobject]@{ number = 2; deviceName = "left"; type = "video"; rotation = "none"; source = "b"; port = 0 }
    )
}
function Get-KioskState { $savedState }
$reused = @(Get-KioskRegistrationDisplays)
Assert-Equal 2 $reused.Count "Registration should reuse every screen from the saved setup."
Assert-Equal "primary" $reused[0].DeviceName "Saved screens keep their device name."
Assert-Equal $true $reused[0].Audio "Saved screens keep which one carries the audio."
Assert-Equal $false $reused[1].Audio "A state file without the audio flag should not fail."
function Get-KioskState { $null }
Assert-Equal $null (Get-KioskRegistrationDisplays) "Without a saved setup there is nothing to reuse."

Assert-Equal "remote-secret" (Unprotect-KioskGuiSecret (Protect-KioskGuiSecret "remote-secret")) "GUI secrets should round-trip through Windows encryption."

Initialize-RotationApi
Assert-Equal 156 ([Runtime.InteropServices.Marshal]::SizeOf([type] [KioskDisplay+DEVMODE])) "The Windows display structure should have the native size."

foreach ($file in @("cleanup.ps1", "cleanup-setup.ps1", "kiosk-gui.ps1")) {
    $tokens = $null
    $errors = $null
    $path = Join-Path $PSScriptRoot "..\$file"
    [void] [Management.Automation.Language.Parser]::ParseFile($path, [ref] $tokens, [ref] $errors)
    Assert-Equal 0 $errors.Count "$file should parse."
}

$runtimeRoot = Join-Path ([IO.Path]::GetTempPath()) ("pi kiosk runtime " + [guid]::NewGuid())
$machineRoot = Join-Path $runtimeRoot "machine"
New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot "app"), $machineRoot | Out-Null
function Find-Edge { "C:\Program Files\Microsoft\Edge\Application\msedge.exe" }
function Find-Vlc { "C:\Program Files\VideoLAN\VLC\vlc.exe" }
function Get-KioskMachineRoot { $machineRoot }
function Get-KioskRoot { $runtimeRoot }
try {
    $launcher = Write-WebRuntime $runtimeRoot (Join-Path $runtimeRoot "app") 8080
    $twoVideos.Displays[0].Audio = $true
    $twoVideos.Displays[0].Path = 'C:\Videos\first clip.mp4'
    $twoVideos.Displays[1].Path = 'C:\Videos\second clip.mp4'
    $orchestrator = Write-KioskOrchestrator -Displays $twoVideos.Displays -AudioDevice "{0.0.0.00000000}.{abc}"
    foreach ($file in @(
        $launcher,
        $orchestrator,
        (Join-Path $runtimeRoot "bin\webapp-server.ps1"),
        (Join-Path $runtimeRoot "bin\cursor-idle.ps1")
    )) {
        $tokens = $null
        $errors = $null
        [void] [Management.Automation.Language.Parser]::ParseFile($file, [ref] $tokens, [ref] $errors)
        Assert-Equal 0 $errors.Count "Generated runtime script $file should parse."
    }
    $generated = Get-Content -Raw $orchestrator
    $header = $generated.Split(@('Add-Type -AssemblyName System.Windows.Forms'), [StringSplitOptions]::None)[0]
    Invoke-Expression $header
    Assert-Equal 2 $items.Count "The generated launcher should parse two videos as two separate items."
    Assert-Equal 1 $items[0].number "The first player should receive only the first display."
    Assert-Equal 2 $items[1].number "The second player should receive only the second display."
    $launcherAst = [Management.Automation.Language.Parser]::ParseInput($generated, [ref] $tokens, [ref] $errors)
    $playerFunction = $launcherAst.Find({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-KioskPlayer'
    }, $true)
    Invoke-Expression $playerFunction.Extent.Text
    function Get-KioskScreenNumber { param([string] $DeviceName) if ($DeviceName -eq 'primary') { 0 } else { 1 } }
    function Test-KioskAudioDevice { param([string] $Id) $false }
    function Start-Process {
        param([string] $FilePath, [string[]] $ArgumentList, [switch] $PassThru)
        $script:playerArgs = $ArgumentList
        [pscustomobject]@{ Id = 42 }
    }
    [void] (Start-KioskPlayer $items[0] $true)
    Assert-Equal '"C:\Videos\first clip.mp4"' $script:playerArgs[-1] "Paths with spaces must stay one VLC argument."
    Assert-Equal $true ($script:playerArgs -contains '--no-one-instance') "Each display needs an independent VLC process."
    Assert-Equal $true ($script:playerArgs -contains '--qt-fullscreen-screennumber=0') "The first video goes to the first screen."
    [void] (Start-KioskPlayer $items[1] $true)
    Assert-Equal '"C:\Videos\second clip.mp4"' $script:playerArgs[-1] "The second player gets only its video."
    Assert-Equal $true ($script:playerArgs -contains '--qt-fullscreen-screennumber=1') "The second video goes to the second screen."
    Assert-Match "qt-fullscreen-screennumber" $generated "The orchestrator should place each video on its own screen."
    Assert-Match "start-paused" $generated "Several videos should be held until every player is ready."
    Assert-Match "kiosk-start-error.log" $generated "Launcher errors should be saved even when started in the background."
    Assert-Match "primary" $generated "The orchestrator should target each configured display by name."
    Assert-Match "left" $generated "The orchestrator should target each configured display by name."
    Assert-Match "--no-audio" $generated "Screens without the audio should be muted."
    Assert-Match "mmdevice-audio-device" $generated "The chosen output should reach the player that carries the audio."
    Assert-Match '"audio":true' $generated "Exactly one screen should be marked as carrying the audio."
    Assert-Equal 1 ([regex]::Matches($generated, '"audio":true').Count) "Only one screen may carry the audio."
} finally {
    Remove-Item -Recurse -Force $runtimeRoot -ErrorAction SilentlyContinue
}

Write-Host "Windows kiosk tests passed."

param(
    [string] $Command = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$script:WindowsRoot = $PSScriptRoot
$script:SharedConfig = $null
$script:Reports = [System.Collections.Generic.List[string]]::new()

foreach ($file in @(
    "src\core.ps1",
    "src\ui.ps1",
    "src\sources.ps1",
    "src\steps\rotation.ps1",
    "src\steps\touch.ps1",
    "src\steps\nosleep.ps1",
    "src\steps\autologin.ps1",
    "src\steps\rustdesk.ps1",
    "src\steps\webapp.ps1",
    "src\steps\video.ps1",
    "src\steps\registration.ps1",
    "src\steps\final-action.ps1",
    "src\app.ps1"
)) {
    . (Join-Path $script:WindowsRoot $file)
}

if ($MyInvocation.InvocationName -ne ".") {
    exit (Invoke-KioskMain)
}

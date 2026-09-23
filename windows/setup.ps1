Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$archiveUrl = if ($env:PI_KIOSK_ARCHIVE_URL) {
    $env:PI_KIOSK_ARCHIVE_URL
} else {
    "https://github.com/Visivalab/pi-kiosk/archive/refs/heads/master.zip"
}
$work = Join-Path ([IO.Path]::GetTempPath()) ("pi-kiosk-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $archive = Join-Path $work "pi-kiosk.zip"
    Write-Host "[....] Downloading Windows kiosk setup"
    Invoke-WebRequest -UseBasicParsing -Uri $archiveUrl -OutFile $archive
    Expand-Archive -Path $archive -DestinationPath $work -Force
    $entry = Get-ChildItem -Recurse -File -Filter kiosk.ps1 $work |
        Where-Object { $_.FullName -like "*\windows\kiosk.ps1" } |
        Select-Object -First 1
    if (-not $entry) { throw "Downloaded archive did not contain windows\kiosk.ps1." }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $entry.FullName
    if ($LASTEXITCODE -ne 0) { throw "Windows kiosk setup failed with exit code $LASTEXITCODE." }
} finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}

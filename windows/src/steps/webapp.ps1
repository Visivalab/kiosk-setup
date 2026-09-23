function Expand-SafeZip {
    param([string] $Archive, [string] $Destination)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $root = [IO.Path]::GetFullPath($Destination).TrimEnd("\") + "\"
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $relative = $entry.FullName.Replace("/", "\")
            if (-not $relative) { continue }
            if ([IO.Path]::IsPathRooted($relative) -or ($relative -split "\\") -contains "..") {
                throw "Webapp ZIP contained an unsafe path."
            }
            if ((($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) {
                throw "Webapp ZIP contained a symbolic link, which is not supported."
            }
            $target = [IO.Path]::GetFullPath((Join-Path $Destination $relative))
            if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Webapp ZIP contained an unsafe path."
            }
            if (-not $entry.Name) {
                New-Item -ItemType Directory -Force -Path $target | Out-Null
                continue
            }
            New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
        }
    } finally { $zip.Dispose() }
}

function Resolve-WebAppRoot {
    param([string] $Root)
    $current = Get-Item $Root
    while ($true) {
        if (Test-Path (Join-Path $current.FullName "index.html") -PathType Leaf) { return $current.FullName }
        $entries = @(Get-ChildItem -Force $current.FullName | Where-Object { $_.Name -notin @("__MACOSX", ".DS_Store") })
        if ($entries.Count -eq 1 -and $entries[0].PSIsContainer) { $current = $entries[0]; continue }
        throw "Webapp ZIP did not contain index.html at the archive root."
    }
}

function Lock-KioskWebApp {
    param([string] $Root)
    $block = @'
<style id="pi-kiosk-lockdown">
  * { -webkit-user-select: none !important; user-select: none !important; -webkit-touch-callout: none !important; }
</style>
<script>window.addEventListener("contextmenu", event => event.preventDefault(), true);</script>
'@
    foreach ($file in Get-ChildItem -Recurse -File -Filter *.html $Root) {
        $html = Get-Content -Raw $file.FullName
        if ($html.Contains('id="pi-kiosk-lockdown"')) { continue }
        if ($html -match "(?i)<head[^>]*>") {
            $html = $html -replace "(?i)(<head[^>]*>)", "`$1`r`n$block"
        } else { $html = "$block`r`n$html" }
        Set-Content -Encoding UTF8 -Path $file.FullName -Value $html
    }
}

function Find-Edge {
    foreach ($path in @(
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
    )) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    throw "Microsoft Edge was not found. Install Edge and run setup again."
}

function Write-WebRuntime {
    param([string] $Root, [string] $AppDir)
    $bin = Join-Path $Root "bin"
    $logs = Join-Path $Root "logs"
    New-Item -ItemType Directory -Force -Path $bin, $logs | Out-Null
    $server = Join-Path $bin "webapp-server.ps1"
    $cursor = Join-Path $bin "cursor-idle.ps1"
    Copy-Item (Join-Path $script:WindowsRoot "runtime\webapp-server.ps1") $server -Force
    Copy-Item (Join-Path $script:WindowsRoot "runtime\cursor-idle.ps1") $cursor -Force

    $launcher = Join-Path $bin "webapp-kiosk.ps1"
    $edge = Find-Edge
    $serverLog = Join-Path $logs "webapp-server.log"
    $profile = Join-Path $Root "edge-profile"
    $reporter = Join-Path (Get-KioskMachineRoot) "totem-status.ps1"
    $reporterConfig = Join-Path (Get-KioskMachineRoot) "totem-status.json"
    @"
param([switch] `$ServerOnly)
`$ErrorActionPreference = "Stop"
`$serverArgs = '-NoProfile -ExecutionPolicy Bypass -File "$server" -Root "$AppDir" -Port 8080 -Log "$serverLog"'
`$serverProcess = Start-Process powershell.exe -ArgumentList `$serverArgs -WindowStyle Hidden -PassThru
try {
  for (`$i=0; `$i -lt 50; `$i++) { try { `$client=[Net.Sockets.TcpClient]::new(); `$client.Connect('127.0.0.1',8080); `$client.Dispose(); break } catch { Start-Sleep -Milliseconds 200 } }
  if ((Test-Path '$reporter') -and (Test-Path '$reporterConfig')) { Start-Process powershell.exe -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File "$reporter" -ConfigPath "$reporterConfig"' -WindowStyle Hidden }
  if (`$ServerOnly) { Wait-Process -Id `$serverProcess.Id; exit }
  `$cursor = Start-Process powershell.exe -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File "$cursor"' -WindowStyle Hidden -PassThru
  try {
    `$browser = Start-Process -FilePath '$edge' -ArgumentList @('--kiosk','http://127.0.0.1:8080','--edge-kiosk-type=fullscreen','--no-first-run','--user-data-dir=$profile') -PassThru
    Wait-Process -Id `$browser.Id
  } finally { Stop-Process -Id `$cursor.Id -Force -ErrorAction SilentlyContinue }
} finally { Stop-Process -Id `$serverProcess.Id -Force -ErrorAction SilentlyContinue }
"@ | Set-Content -Encoding UTF8 $launcher
    $launcher
}

function Install-KioskWebApp {
    param([string] $SourceUrl)
    $root = Get-KioskRoot
    $webRoot = Join-Path $root "webapp"
    $next = Join-Path $webRoot "next"
    $current = Join-Path $webRoot "current"
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("pi-kiosk-web-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Force -Path $temp, $next | Out-Null
    try {
        $archive = Join-Path $temp "webapp.zip"
        Write-KioskProgress "Downloading webapp ZIP"
        Invoke-WebRequest -UseBasicParsing -Uri $SourceUrl -OutFile $archive
        $extracted = Join-Path $temp "extracted"
        Write-KioskProgress "Extracting webapp files"
        Expand-SafeZip $archive $extracted
        $sourceRoot = Resolve-WebAppRoot $extracted
        Remove-Item -Recurse -Force $next -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $next | Out-Null
        Get-ChildItem -Force $sourceRoot | Copy-Item -Destination $next -Recurse -Force
        Lock-KioskWebApp $next
        Remove-Item -Recurse -Force $current -ErrorAction SilentlyContinue
        Move-Item $next $current
    } finally { Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue }

    & netsh.exe http delete urlacl url=http://127.0.0.1:8080/ 2>$null | Out-Null
    & netsh.exe http add urlacl url=http://127.0.0.1:8080/ "user=$env:USERDOMAIN\$env:USERNAME" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not reserve http://127.0.0.1:8080/ for the kiosk user." }
    $launcher = Write-WebRuntime $root $current
    Set-KioskStartup $launcher
    Write-KioskDone "webapp kiosk deployed from $SourceUrl to $current. Edge will start on the next login."
    [pscustomobject]@{ Type = "webapp"; Launcher = $launcher; Source = $SourceUrl; Path = $current }
}

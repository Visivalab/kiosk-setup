function Find-Vlc {
    foreach ($path in @(
        "$env:ProgramFiles\VideoLAN\VLC\vlc.exe",
        "${env:ProgramFiles(x86)}\VideoLAN\VLC\vlc.exe"
    )) { if ($path -and (Test-Path $path)) { return $path } }
    $null
}

function Install-KioskVideo {
    param([string] $SourceUrl)
    $vlc = Find-Vlc
    if (-not $vlc) {
        if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw "VLC is missing and winget is unavailable." }
        Write-KioskProgress "Installing VLC"
        & winget.exe install --id VideoLAN.VLC --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "winget could not install VLC." }
        $vlc = Find-Vlc
    }
    if (-not $vlc) { throw "VLC was installed but vlc.exe could not be found." }

    $root = Get-KioskRoot
    $videoRoot = Join-Path $root "video"
    $next = Join-Path $videoRoot "next"
    $current = Join-Path $videoRoot "current"
    Remove-Item -Recurse -Force $next -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $next | Out-Null
    $download = Join-Path $next "video-download"
    Write-KioskProgress "Downloading video"
    $response = Invoke-WebRequest -UseBasicParsing -Uri $SourceUrl -OutFile $download -PassThru
    $type = [string] $response.Headers["Content-Type"]
    if ($type -and $type -notmatch "^(video/|application/octet-stream|application/mp4)") {
        throw "Dropbox did not return a video file. Got Content-Type $type."
    }
    $name = [IO.Path]::GetFileName(([uri] $SourceUrl).AbsolutePath)
    $disposition = [string] $response.Headers["Content-Disposition"]
    if ($disposition -match "filename\*=UTF-8''([^;]+)") { $name = [uri]::UnescapeDataString($matches[1].Trim('"')) }
    elseif ($disposition -match 'filename="?([^";]+)') { $name = $matches[1] }
    if (-not $name) { $name = "video.mp4" }
    $video = Join-Path $next ([IO.Path]::GetFileName($name))
    Move-Item $download $video
    if ((Get-Item $video).Length -eq 0) { throw "Downloaded video file was empty." }
    Remove-Item -Recurse -Force $current -ErrorAction SilentlyContinue
    Move-Item $next $current
    $video = Join-Path $current ([IO.Path]::GetFileName($name))

    $bin = Join-Path $root "bin"
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $launcher = Join-Path $bin "video-kiosk.ps1"
    @"
`$player = Start-Process -FilePath '$vlc' -ArgumentList @('--fullscreen','--loop','--no-video-title-show','--no-qt-fs-controller','--mouse-hide-timeout=0','$video') -PassThru
Wait-Process -Id `$player.Id
"@ | Set-Content -Encoding UTF8 $launcher
    Set-KioskStartup $launcher
    Write-KioskDone "video kiosk deployed to $video. VLC will start on the next login."
    [pscustomobject]@{ Type = "video"; Launcher = $launcher; Source = $SourceUrl; Path = $video }
}

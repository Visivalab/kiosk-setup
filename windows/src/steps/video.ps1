function Find-Vlc {
    foreach ($path in @(
        "$env:ProgramFiles\VideoLAN\VLC\vlc.exe",
        "${env:ProgramFiles(x86)}\VideoLAN\VLC\vlc.exe"
    )) { if ($path -and (Test-Path $path)) { return $path } }
    $null
}

function Install-Vlc {
    $vlc = Find-Vlc
    if (-not $vlc) {
        if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw "VLC is missing and winget is unavailable." }
        Write-KioskProgress "Installing VLC"
        & winget.exe install --id VideoLAN.VLC --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "winget could not install VLC." }
        $vlc = Find-Vlc
    }
    if (-not $vlc) { throw "VLC was installed but vlc.exe could not be found." }
    $vlc
}

function Install-KioskVideo {
    param([Parameter(Mandatory = $true)][object] $Display)

    [void] (Install-Vlc)

    $videoRoot = Join-Path (Get-KioskRoot) "video\display-$($Display.Number)"
    $next = Join-Path $videoRoot "next"
    $current = Join-Path $videoRoot "current"
    Remove-Item -Recurse -Force $next -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $next | Out-Null
    $download = Join-Path $next "video-download"
    Write-KioskProgress "Downloading video for display $($Display.Number)"
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Display.Url -OutFile $download -PassThru
    $type = [string] $response.Headers["Content-Type"]
    if ($type -and $type -notmatch "^(video/|application/octet-stream|application/mp4)") {
        throw "Dropbox did not return a video file. Got Content-Type $type."
    }
    $name = [IO.Path]::GetFileName(([uri] $Display.Url).AbsolutePath)
    $disposition = [string] $response.Headers["Content-Disposition"]
    if ($disposition -match "filename\*=UTF-8''([^;]+)") { $name = [uri]::UnescapeDataString($matches[1].Trim('"')) }
    elseif ($disposition -match 'filename="?([^";]+)') { $name = $matches[1] }
    if (-not $name) { $name = "video.mp4" }
    $video = Join-Path $next ([IO.Path]::GetFileName($name))
    Move-Item $download $video
    if ((Get-Item $video).Length -eq 0) { throw "Downloaded video file was empty." }
    Remove-Item -Recurse -Force $current -ErrorAction SilentlyContinue
    Move-Item $next $current

    $Display.Path = Join-Path $current ([IO.Path]::GetFileName($name))
    Write-KioskDone "video kiosk for display $($Display.Number) deployed to $($Display.Path)."
    $Display
}

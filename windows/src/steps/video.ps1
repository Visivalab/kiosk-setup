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

function Assert-KioskVideoContentType {
    param([AllowEmptyString()][string] $ContentType)

    # Dropbox serves some valid MP4 downloads as application/binary.
    if ($ContentType -and $ContentType -notmatch '^(video/[^;\s]+|application/(octet-stream|mp4|binary))(\s*;|$)') {
        throw "Dropbox did not return a video file. Got Content-Type $ContentType."
    }
}

function Get-KioskCachedVideo {
    param([object] $Display, [string] $Current)

    $state = Get-KioskState
    if (-not $state) { return $null }
    $directory = [IO.Path]::GetFullPath($Current)
    foreach ($saved in @($state.displays)) {
        if ([int] $saved.number -ne $Display.Number -or
            [string] $saved.deviceName -ne $Display.DeviceName -or
            [string] $saved.type -ne 'video') { continue }
        try {
            if ((Normalize-VideoSource ([string] $saved.source)) -cne $Display.Url) { continue }
            $path = [IO.Path]::GetFullPath([string] $saved.path)
        } catch { continue }
        if (-not [string]::Equals([IO.Path]::GetDirectoryName($path), $directory,
                [StringComparison]::OrdinalIgnoreCase)) { continue }
        if ((Test-Path -LiteralPath $path -PathType Leaf) -and (Get-Item -LiteralPath $path).Length -gt 0) {
            return $path
        }
    }
    $null
}

function Install-KioskVideo {
    param([Parameter(Mandatory = $true)][object] $Display)

    [void] (Install-Vlc)

    $videoRoot = Join-Path (Get-KioskRoot) "video\display-$($Display.Number)"
    $next = Join-Path $videoRoot "next"
    $current = Join-Path $videoRoot "current"
    $cached = Get-KioskCachedVideo $Display $current
    if ($cached) {
        $Display.Path = $cached
        Write-KioskDone "reusing the existing video for display $($Display.Number) at $cached."
        return $Display
    }
    Remove-Item -Recurse -Force $next -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $next | Out-Null
    $download = Join-Path $next "video-download"
    Write-KioskProgress "Downloading video for display $($Display.Number)"
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Display.Url -OutFile $download -PassThru
    Assert-KioskVideoContentType ([string] $response.Headers["Content-Type"])
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

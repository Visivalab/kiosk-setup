function Normalize-WebAppSource {
    param([string] $Value)
    $path = $Value.Trim()
    $parts = $path -split "/"
    if ($parts.Count -lt 2 -or $parts[-1] -notmatch "(?i)^.+\.zip$") {
        throw "Enter an S3 ZIP path, for example $($script:SharedConfig.webappPathExample)."
    }
    foreach ($part in $parts) {
        if (-not $part -or $part -in @(".", "..") -or $part -notmatch "^[A-Za-z0-9._-]+$") {
            throw "Enter an S3 ZIP path, for example $($script:SharedConfig.webappPathExample)."
        }
    }
    "$($script:SharedConfig.s3ReleaseBaseUrl)$path"
}

function Normalize-VideoSource {
    param([string] $Value)
    $text = $Value.Trim()
    try { $uri = [uri] $text } catch { throw "Enter a valid Dropbox shared file link over HTTPS." }
    $hostName = $uri.Host.ToLowerInvariant()
    if ($uri.Scheme -ne "https" -or ($hostName -ne "dropbox.com" -and -not $hostName.EndsWith(".dropbox.com"))) {
        throw "Enter a valid Dropbox shared file link over HTTPS."
    }
    if ($uri.AbsolutePath -notmatch "^/s/[^/]+/[^/]+" -and $uri.AbsolutePath -notmatch "^/scl/fi/[^/]+/[^/]+") {
        throw "Enter a valid Dropbox shared file link."
    }
    $builder = [UriBuilder]::new($uri)
    $query = @($builder.Query.TrimStart("?").Split([char[]] "&", [StringSplitOptions]::RemoveEmptyEntries) |
        Where-Object { [uri]::UnescapeDataString(($_ -split "=", 2)[0]) -ne "dl" })
    $builder.Query = (@($query) + "dl=1") -join "&"
    $builder.Uri.AbsoluteUri
}

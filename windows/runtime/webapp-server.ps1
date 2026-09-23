param([string] $Root, [int] $Port = 8080, [string] $Log)

$ErrorActionPreference = "Stop"
$listener = [Net.HttpListener]::new()
$listener.Prefixes.Add("http://127.0.0.1:$Port/")
$mime = @{ ".html"="text/html; charset=utf-8"; ".js"="text/javascript; charset=utf-8"; ".css"="text/css; charset=utf-8"; ".json"="application/json; charset=utf-8"; ".svg"="image/svg+xml"; ".png"="image/png"; ".jpg"="image/jpeg"; ".jpeg"="image/jpeg"; ".gif"="image/gif"; ".webp"="image/webp"; ".woff2"="font/woff2"; ".mp4"="video/mp4" }
$rootPath = [IO.Path]::GetFullPath($Root).TrimEnd("\") + "\"
try {
    $listener.Start()
    Add-Content $Log "$(Get-Date -Format o) server listening on http://127.0.0.1:$Port"
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        try {
            $requestPath = [Uri]::UnescapeDataString($context.Request.Url.AbsolutePath).TrimStart("/")
            if (-not $requestPath) { $requestPath = "index.html" }
            $path = [IO.Path]::GetFullPath((Join-Path $Root $requestPath.Replace("/", "\")))
            if (-not $path.StartsWith($rootPath, [StringComparison]::OrdinalIgnoreCase)) { throw "unsafe path" }
            if (Test-Path $path -PathType Container) { $path = Join-Path $path "index.html" }
            if ($context.Request.HttpMethod -notin @("GET", "HEAD") -or -not (Test-Path $path -PathType Leaf)) {
                $context.Response.StatusCode = 404
            } else {
                $bytes = [IO.File]::ReadAllBytes($path)
                $type = $mime[[IO.Path]::GetExtension($path).ToLowerInvariant()]
                if ($type) { $context.Response.ContentType = $type }
                else { $context.Response.ContentType = "application/octet-stream" }
                $context.Response.ContentLength64 = $bytes.Length
                if ($context.Request.HttpMethod -ne "HEAD") {
                    $context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
                }
            }
        } catch {
            $context.Response.StatusCode = 404
        } finally {
            $context.Response.Close()
        }
    }
} finally {
    $listener.Close()
}

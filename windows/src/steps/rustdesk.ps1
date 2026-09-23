function Find-RustDesk {
    $command = Get-Command rustdesk.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($path in @(
        "$env:ProgramFiles\RustDesk\RustDesk.exe",
        "${env:ProgramFiles(x86)}\RustDesk\RustDesk.exe"
    )) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    $null
}

function Install-KioskRustDesk {
    param([string] $Password)
    $rustdesk = Find-RustDesk
    if (-not $rustdesk) {
        if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
            throw "RustDesk is missing and winget is not available. Install App Installer and run setup again."
        }
        Write-KioskProgress "Installing RustDesk"
        & winget.exe install --id RustDesk.RustDesk --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "winget could not install RustDesk." }
        $rustdesk = Find-RustDesk
    }
    if (-not $rustdesk) { throw "RustDesk was installed but RustDesk.exe could not be found." }

    Write-KioskProgress "Configuring RustDesk unattended access"
    & $rustdesk --option approve-mode password | Out-Null
    & $rustdesk --option verification-method use-permanent-password | Out-Null
    & $rustdesk --password $Password | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "RustDesk did not accept the unattended password." }
    $id = (& $rustdesk --get-id | Out-String).Trim()
    if (-not $id) { throw "RustDesk did not return an ID." }

    $credentials = Join-Path (Get-KioskMachineRoot) "rustdesk.json"
    @{ password = $Password; id = $id } | ConvertTo-Json | Set-Content -Encoding UTF8 -Path $credentials
    Protect-KioskFile $credentials
    Write-KioskDone "RustDesk installed and configured. ID: $id"
    [pscustomobject]@{ Id = $id; Password = $Password }
}

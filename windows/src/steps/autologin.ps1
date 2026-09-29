function Enable-KioskAutologon {
    $prompt = "Windows password for $env:USERDOMAIN\$env:USERNAME. Use the account password, not the PIN. Leave blank only if this local account has no password"
    $password = Read-KioskSecret $prompt -AllowEmpty
    if (-not $password) {
        if ($env:USERDOMAIN -ne $env:COMPUTERNAME) {
            throw "A blank password can only be used with a local Windows account."
        }
        $winlogon = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
        New-ItemProperty -Path $winlogon -Name DefaultUserName -Value $env:USERNAME -PropertyType String -Force | Out-Null
        New-ItemProperty -Path $winlogon -Name DefaultDomainName -Value $env:COMPUTERNAME -PropertyType String -Force | Out-Null
        New-ItemProperty -Path $winlogon -Name DefaultPassword -Value "" -PropertyType String -Force | Out-Null
        New-ItemProperty -Path $winlogon -Name AutoAdminLogon -Value "1" -PropertyType String -Force | Out-Null
        Write-KioskDone "desktop autologin is enabled for $env:COMPUTERNAME\$env:USERNAME without a password."
        return
    }

    Write-KioskProgress "Downloading Microsoft Sysinternals Autologon"
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("pi-kiosk-autologon-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $temp | Out-Null
    try {
        $zip = Join-Path $temp "Autologon.zip"
        Invoke-WebRequest -UseBasicParsing -Uri "https://download.sysinternals.com/files/Autologon.zip" -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath $temp -Force
        $exe = Join-Path $temp "Autologon64.exe"
        if (-not (Test-Path $exe)) { throw "The Autologon download did not contain Autologon64.exe." }
        & $exe -accepteula $env:USERNAME $env:USERDOMAIN $password | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Microsoft Autologon failed with exit code $LASTEXITCODE." }
    } finally {
        $password = $null
        Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
    }
    Write-KioskDone "desktop autologin is enabled for $env:USERDOMAIN\$env:USERNAME. The account password still exists."
}

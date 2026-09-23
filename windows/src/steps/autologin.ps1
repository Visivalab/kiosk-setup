function Enable-KioskAutologon {
    $password = Read-KioskSecret "Windows password for $env:USERDOMAIN\$env:USERNAME"
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

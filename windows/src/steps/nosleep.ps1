function Set-KioskNoSleep {
    foreach ($setting in @(
        @("monitor-timeout-ac", "0"), @("monitor-timeout-dc", "0"),
        @("standby-timeout-ac", "0"), @("standby-timeout-dc", "0"),
        @("hibernate-timeout-ac", "0"), @("hibernate-timeout-dc", "0")
    )) {
        & powercfg.exe /change $setting[0] $setting[1]
        if ($LASTEXITCODE -ne 0) { throw "powercfg failed while setting $($setting[0])." }
    }
    $desktop = "HKCU:\Control Panel\Desktop"
    Set-ItemProperty -Path $desktop -Name ScreenSaveActive -Value "0"
    Write-KioskDone "screen blanking and sleep are disabled."
}

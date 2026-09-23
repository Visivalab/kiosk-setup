function Show-KioskSummary {
    Write-Host ""
    Write-Host "Done: setup summary"
    Write-Host ""
    foreach ($report in $script:Reports) { Write-Host ("- [x] " + $report.Substring(6)) }
}

function Invoke-KioskFinalAction {
    param([object] $Kiosk)
    if ($Kiosk.Type -eq "webapp") {
        $choice = Read-KioskChoice $script:SharedConfig.prompts.nextAction @(
            "Simulate autorun - just for testing",
            "Reboot - final production",
            "Close - keep the app server running without opening Edge"
        )
        if ($choice -eq 0) { Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($Kiosk.Launcher)`""; Write-KioskDone "launched the webapp kiosk for testing." }
        elseif ($choice -eq 1) { Restart-Computer -Force }
        else { Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($Kiosk.Launcher)`" -ServerOnly" -WindowStyle Hidden; Write-KioskDone "the app is live on http://127.0.0.1:8080 without opening Edge." }
    } else {
        $videoChoices = $script:SharedConfig.choices.videoAction
        $choice = Read-KioskChoice $script:SharedConfig.prompts.videoNextAction @($videoChoices.launch, $videoChoices.reboot, $videoChoices.nothing)
        if ($choice -eq 0) { Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($Kiosk.Launcher)`""; Write-KioskDone "launching video now for testing." }
        elseif ($choice -eq 1) { Restart-Computer -Force }
        else { Write-KioskDone "doing nothing now." }
    }
}

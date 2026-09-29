function Show-KioskSummary {
    Write-Host ""
    Write-Host "Done: setup summary"
    Write-Host ""
    foreach ($report in $script:Reports) { Write-Host ("- [x] " + $report.Substring(6)) }
}

function Invoke-KioskFinalAction {
    [CmdletBinding()]
    param([object] $Kiosk, [string] $Action)

    if (-not $PSBoundParameters.ContainsKey("Action")) {
        if ($Kiosk.Type -eq "webapp") {
            $choice = Read-KioskChoice $script:SharedConfig.prompts.nextAction @(
                "Simulate autorun - just for testing",
                "Reboot - final production",
                "Close - keep the app server running without opening Edge"
            )
        } else {
            $videoChoices = $script:SharedConfig.choices.videoAction
            $choice = Read-KioskChoice $script:SharedConfig.prompts.videoNextAction @($videoChoices.launch, $videoChoices.reboot, $videoChoices.nothing)
        }
        $Action = @("launch", "reboot", "nothing")[$choice]
    }
    if ($Action -notin @("launch", "reboot", "nothing")) { throw "Unknown final action: $Action" }

    if ($Action -eq "launch") {
        Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($Kiosk.Launcher)`""
        Write-KioskDone "launching the $($Kiosk.Type) kiosk now for testing."
    } elseif ($Action -eq "reboot") {
        Restart-Computer -Force
    } elseif ($Kiosk.Type -eq "webapp") {
        Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($Kiosk.Launcher)`" -ServerOnly" -WindowStyle Hidden
        Write-KioskDone "the app is live on http://127.0.0.1:8080 without opening Edge."
    } else {
        Write-KioskDone "doing nothing now."
    }
}

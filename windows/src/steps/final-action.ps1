function Show-KioskSummary {
    Write-Host ""
    Write-Host "Done: setup summary"
    Write-Host ""
    foreach ($report in $script:Reports) { Write-Host ("- [x] " + $report.Substring(6)) }
}

function Invoke-KioskFinalAction {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object] $Plan,
        [Parameter(Mandatory = $true)][string] $Launcher,
        [string] $Action
    )

    $displays = @($Plan.Displays)
    $webapp = @($displays | Where-Object { $_.Type -eq "webapp" })

    if (-not $PSBoundParameters.ContainsKey("Action")) {
        if ($webapp.Count -gt 0) {
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
        Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`""
        $what = if ($displays.Count -gt 1) { "$($displays.Count) kiosk screens" } else { "the $($displays[0].Type) kiosk" }
        Write-KioskDone "launching $what now for testing."
    } elseif ($Action -eq "reboot") {
        Restart-Computer -Force
    } elseif ($webapp.Count -gt 0) {
        Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($webapp[0].Launcher)`" -ServerOnly" -WindowStyle Hidden
        Write-KioskDone "the app is live on http://127.0.0.1:$($webapp[0].Port) without opening Edge."
    } else {
        Write-KioskDone "doing nothing now."
    }
}

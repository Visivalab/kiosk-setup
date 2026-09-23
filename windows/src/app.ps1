function Invoke-KioskWizard {
    param([object] $Display)
    if (-not (Test-KioskAdministrator)) {
        throw "Run Windows Terminal as Administrator. Nothing was changed."
    }
    $script:SharedConfig = Get-KioskSharedConfig

    $rotationChoices = $script:SharedConfig.choices.rotation
    $rotationIndex = Read-KioskChoice $script:SharedConfig.prompts.screenRotation @($rotationChoices.none, $rotationChoices.clockwise, $rotationChoices.counterclockwise)
    $rotation = @("none", "clockwise", "counterclockwise")[$rotationIndex]
    Set-KioskRotation $Display $rotation
    Test-KioskTouchscreen
    Set-KioskNoSleep
    Enable-KioskAutologon
    $rustdeskPassword = Read-KioskSecret $script:SharedConfig.prompts.rustdeskPassword
    [void] (Install-KioskRustDesk $rustdeskPassword)

    $projectChoices = $script:SharedConfig.choices.project
    $projectIndex = Read-KioskChoice $script:SharedConfig.prompts.projectType @($projectChoices.webapp, $projectChoices.video)
    if ($projectIndex -eq 0) {
        $webPrompt = $script:SharedConfig.prompts.webappSource.Replace("{example}", $script:SharedConfig.webappPathExample)
        while ($true) {
            try { $source = Normalize-WebAppSource (Read-Host $webPrompt); break }
            catch { Write-Host "WARN: $($_.Exception.Message)" -ForegroundColor Yellow }
        }
        $kiosk = Install-KioskWebApp $source
    } else {
        while ($true) {
            try { $source = Normalize-VideoSource (Read-Host $script:SharedConfig.prompts.videoSource); break }
            catch { Write-Host "WARN: $($_.Exception.Message)" -ForegroundColor Yellow }
        }
        $kiosk = Install-KioskVideo $source
    }
    Register-KioskTotem $kiosk.Type
    Show-KioskSummary
    Invoke-KioskFinalAction $kiosk
}

function Invoke-KioskMain {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $displays = @(Get-KioskDisplays)
        if ($displays.Count -eq 0) { throw "No active displays were detected." }
        Write-Host "Detected displays"
        Write-Host ""
        foreach ($display in $displays) { Write-Host (Format-KioskDisplay $display) }
        Write-Host ""
        if ($displays.Count -gt 1) {
            Write-Host "Multiple-screen configuration is not available yet. Nothing was changed."
            return 0
        }
        Invoke-KioskWizard $displays[0]
        return 0
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        return 1
    }
}

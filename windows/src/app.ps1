function Invoke-KioskPlan {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object] $Plan, [switch] $PromptFinalAction)

    if (-not (Test-KioskAdministrator)) {
        throw "Run Windows Terminal as Administrator. Nothing was changed."
    }
    $validationError = Test-KioskPlan $Plan
    if ($validationError) { throw $validationError }
    [void] (Resolve-KioskPlan $Plan)

    Set-KioskRotationPlan $Plan.Displays
    Set-KioskNoSleep
    Enable-KioskAutologon -Password $Plan.WindowsPassword
    Set-KioskRustDeskAccess $Plan

    Install-KioskContent $Plan

    Resolve-KioskAudioPlan $Plan
    $launcher = Write-KioskOrchestrator -Displays $Plan.Displays -AudioDevice $Plan.AudioDevice
    Set-KioskStartup $launcher
    [void] (Save-KioskState $Plan $launcher)
    $screens = if (@($Plan.Displays).Count -gt 1) { "$(@($Plan.Displays).Count) screens" } else { "one screen" }
    Write-KioskDone "kiosk startup installed for $screens. It starts on the next login."

    if ($Plan.Register) {
        Register-KioskTotem -TotemType (Get-KioskPlanTotemType $Plan) -Displays $Plan.Displays `
            -Name $Plan.TotemName -Description $Plan.TotemDescription -Location $Plan.TotemLocation `
            -SkipRustDesk:$($Plan.SkipRustDesk)
    } else {
        Write-KioskDone "skipped totem registration."
    }
    Show-KioskSummary
    if ($PromptFinalAction) {
        Invoke-KioskFinalAction -Plan $Plan -Launcher $launcher
    } else {
        Invoke-KioskFinalAction -Plan $Plan -Launcher $launcher -Action $Plan.FinalAction
    }
}

function Set-KioskRustDeskAccess {
    param([Parameter(Mandatory = $true)][object] $Plan)

    if ($Plan.SkipRustDesk) {
        Write-KioskDone "skipped RustDesk setup; remote access will not be available."
    } else {
        [void] (Install-KioskRustDesk $Plan.RustDeskPassword)
    }
}

function Install-KioskContent {
    param([Parameter(Mandatory = $true)][object] $Plan)

    try {
        foreach ($display in @($Plan.Displays)) {
            if ($display.Type -eq "webapp") { [void] (Install-KioskWebApp $display) }
            else { [void] (Install-KioskVideo $display) }
        }
    } catch {
        $contentError = $_
        # No startup entry or saved working state is written for an incomplete kiosk.
        if ($Plan.Register) {
            Write-Host "WARN: Kiosk content failed. Attempting to register the totem anyway."
            try {
                Register-KioskTotem -TotemType (Get-KioskPlanTotemType $Plan) -Displays $Plan.Displays `
                    -Name $Plan.TotemName -Description $Plan.TotemDescription -Location $Plan.TotemLocation `
                    -SkipRustDesk:$($Plan.SkipRustDesk)
            } catch {
                Write-Host "WARN: Totem registration or status setup failed; retry it when the connection is available."
            }
        }
        throw $contentError
    }
}

function Read-KioskDisplayPlan {
    param([object] $Display, [bool] $VideoOnly)

    $rotationChoices = $script:SharedConfig.choices.rotation
    $prompt = if ($VideoOnly) {
        "$($script:SharedConfig.prompts.screenRotation) - display $($Display.Number) ($($Display.DeviceName))"
    } else {
        $script:SharedConfig.prompts.screenRotation
    }
    $rotationIndex = Read-KioskChoice $prompt @($rotationChoices.none, $rotationChoices.clockwise, $rotationChoices.counterclockwise)
    $rotation = @("none", "clockwise", "counterclockwise")[$rotationIndex]

    $type = "video"
    if (-not $VideoOnly) {
        $projectChoices = $script:SharedConfig.choices.project
        $projectIndex = Read-KioskChoice $script:SharedConfig.prompts.projectType @($projectChoices.webapp, $projectChoices.video)
        $type = @("webapp", "video")[$projectIndex]
    }

    $sourcePrompt = if ($type -eq "webapp") {
        $script:SharedConfig.prompts.webappSource.Replace("{example}", $script:SharedConfig.webappPathExample)
    } elseif ($VideoOnly) {
        "$($script:SharedConfig.prompts.videoSource) or absolute local video path - display $($Display.Number)"
    } else {
        "$($script:SharedConfig.prompts.videoSource) or absolute local video path"
    }
    while ($true) {
        $source = (Read-Host $sourcePrompt).Trim()
        try {
            if ($type -eq "webapp") { [void] (Normalize-WebAppSource $source) } else { [void] (Normalize-VideoSource $source) }
            break
        } catch { Write-Host "WARN: $($_.Exception.Message)" -ForegroundColor Yellow }
    }
    New-KioskDisplayPlan $Display -Rotation $rotation -Type $type -Source $source
}

function Read-KioskPlan {
    param([object[]] $Displays)

    $videoOnly = @($Displays).Count -gt 1
    if ($videoOnly) {
        Write-Host "Multiple displays detected. Each display gets its own looping video."
        Write-Host ""
    }
    $planned = @(@($Displays) | ForEach-Object { Read-KioskDisplayPlan $_ $videoOnly })

    $audioDisplay = 0
    $audioDevice = ""
    $audioDeviceName = ""
    $videos = @($planned | Where-Object { $_.Type -eq "video" })
    if ($videos.Count -gt 0) { $audioDisplay = $videos[0].Number }
    if ($videos.Count -gt 1) {
        $labels = @($videos | ForEach-Object { "Display $($_.Number) ($($_.DeviceName))" })
        $audioDisplay = $videos[(Read-KioskChoice "Which video plays the audio? The other screens are muted." $labels)].Number
        $devices = @(Get-KioskAudioDevices)
        if ($devices.Count -gt 0) {
            $options = @("Default output - whatever is available when it plays") + @($devices | ForEach-Object { $_.Name })
            $choice = Read-KioskChoice "Audio output" $options
            if ($choice -gt 0) {
                $audioDevice = $devices[$choice - 1].Id
                $audioDeviceName = $devices[$choice - 1].Name
            }
        }
    }

    $windowsPassword = Read-KioskSecret "Windows password for $env:USERDOMAIN\$env:USERNAME. Use the account password, not the PIN. Leave blank only if this local account has no password" -AllowEmpty
    $rustdeskPassword = Read-KioskConfirmedSecret $script:SharedConfig.prompts.rustdeskPassword

    $register = Read-KioskConfirmation $script:SharedConfig.prompts.registerTotem $true
    $name = ""
    $description = ""
    $location = ""
    if ($register) {
        $name = Read-KioskRequired $script:SharedConfig.prompts.totemName
        $description = (Read-Host $script:SharedConfig.prompts.totemDescription).Trim()
        $location = (Read-Host $script:SharedConfig.prompts.totemLocation).Trim()
    }

    New-KioskPlan -Displays $planned -WindowsPassword $windowsPassword -RustDeskPassword $rustdeskPassword `
        -Register $register -TotemName $name -TotemDescription $description -TotemLocation $location `
        -FinalAction "nothing" -AudioDisplay $audioDisplay -AudioDevice $audioDevice -AudioDeviceName $audioDeviceName
}

function Invoke-KioskWizard {
    param([object[]] $Displays)
    $script:SharedConfig = Get-KioskSharedConfig
    $plan = Read-KioskPlan $Displays
    Invoke-KioskPlan $plan -PromptFinalAction
}

function Invoke-KioskRegisterTotemCommand {
    $script:SharedConfig = Get-KioskSharedConfig
    $type = ""
    if (-not (Get-KioskRegistrationDisplays)) {
        Write-Host "This PC has no saved kiosk setup, so the totem type cannot be reused."
        Write-Host ""
        $projectChoices = $script:SharedConfig.choices.project
        $index = Read-KioskChoice $script:SharedConfig.prompts.totemType @($projectChoices.webapp, $projectChoices.video)
        $type = @("webapp", "video")[$index]
    }
    $name = Read-KioskRequired $script:SharedConfig.prompts.totemName
    $description = (Read-Host $script:SharedConfig.prompts.totemDescription).Trim()
    $location = (Read-Host $script:SharedConfig.prompts.totemLocation).Trim()
    Register-KioskTotemNow -Name $name -Description $description -Location $location -TotemType $type
    Show-KioskSummary
}

function Invoke-KioskMain {
    param([AllowEmptyString()][string] $Command = "")

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        if (-not (Test-KioskAdministrator)) {
            throw "Run Windows Terminal as Administrator. Nothing was changed."
        }
        if ($Command) {
            if ($Command -ne "register-totem") {
                throw "Unknown command: $Command. The only command is register-totem."
            }
            Invoke-KioskRegisterTotemCommand
            return 0
        }
        $displays = @(Get-KioskDisplays)
        if ($displays.Count -eq 0) { throw "No active displays were detected." }
        Write-Host "Detected displays"
        Write-Host ""
        foreach ($display in $displays) { Write-Host (Format-KioskDisplay $display) }
        Write-Host ""
        Invoke-KioskWizard $displays
        return 0
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        return 1
    }
}

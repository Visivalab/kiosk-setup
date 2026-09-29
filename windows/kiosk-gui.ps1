param([string] $ApplyConfig = "", [switch] $Cleanup)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
. (Join-Path $PSScriptRoot "kiosk.ps1")

function Protect-KioskGuiSecret {
    param([AllowEmptyString()][string] $Value)
    if (-not $Value) { return "" }
    ConvertTo-SecureString $Value -AsPlainText -Force | ConvertFrom-SecureString
}

function Unprotect-KioskGuiSecret {
    param([AllowEmptyString()][string] $Value)
    if (-not $Value) { return "" }
    $secure = ConvertTo-SecureString $Value
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function ConvertFrom-KioskGuiConfig {
    param([Parameter(Mandatory = $true)][object] $Config, [object[]] $Detected)

    $planned = @()
    foreach ($entry in @($Config.displays)) {
        $match = @(@($Detected) | Where-Object { $_.DeviceName -eq [string] $entry.deviceName })
        if ($match.Count -ne 1) {
            throw "The connected displays changed since the wizard opened. Nothing was changed."
        }
        $planned += New-KioskDisplayPlan $match[0] `
            -Rotation ([string] $entry.rotation) -Type ([string] $entry.type) -Source ([string] $entry.source)
    }
    if ($planned.Count -ne @($Detected).Count) {
        throw "The connected displays changed since the wizard opened. Nothing was changed."
    }
    New-KioskPlan -Displays $planned `
        -WindowsPassword (Unprotect-KioskGuiSecret ([string] $Config.windowsPassword)) `
        -RustDeskPassword (Unprotect-KioskGuiSecret ([string] $Config.rustDeskPassword)) `
        -Register ([bool] $Config.registerTotem) `
        -TotemName ([string] $Config.totemName) `
        -TotemDescription ([string] $Config.totemDescription) `
        -TotemLocation ([string] $Config.totemLocation) `
        -FinalAction ([string] $Config.finalAction) `
        -AudioDisplay ([int] $Config.audioDisplay) `
        -AudioDevice ([string] $Config.audioDevice) `
        -AudioDeviceName ([string] $Config.audioDeviceName)
}

function Invoke-KioskGuiSetup {
    param([Parameter(Mandatory = $true)][string] $ConfigPath)
    try {
        if (-not (Test-KioskAdministrator)) { throw "Administrator access is required." }
        $script:SharedConfig = Get-KioskSharedConfig
        $config = Get-Content -Raw -Encoding UTF8 $ConfigPath | ConvertFrom-Json
        $plan = ConvertFrom-KioskGuiConfig $config (Get-KioskDisplays)
        Invoke-KioskPlan $plan
        return 0
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        return 1
    } finally {
        Remove-Item -Force $ConfigPath -ErrorAction SilentlyContinue
    }
}

function Invoke-KioskGuiCleanup {
    if (-not (Test-KioskAdministrator)) {
        [Console]::Error.WriteLine("Administrator access is required.")
        return 1
    }
    . (Join-Path $PSScriptRoot "cleanup.ps1")
    Invoke-KioskCleanup
}

function Add-KioskGuiField {
    param(
        [Windows.Forms.TableLayoutPanel] $Table,
        [string] $Text,
        [Windows.Forms.Control] $Control
    )
    $row = $Table.RowCount
    $Table.RowCount++
    [void] $Table.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::AutoSize))
    $label = [Windows.Forms.Label]::new()
    $label.Text = $Text
    $label.AutoSize = $true
    $label.Anchor = "Left"
    $label.Margin = [Windows.Forms.Padding]::new(0, 8, 12, 8)
    $Control.Dock = "Fill"
    $Control.Margin = [Windows.Forms.Padding]::new(0, 4, 0, 4)
    $Control.AccessibleName = $Text.TrimEnd(":")
    $Table.Controls.Add($label, 0, $row)
    $Table.Controls.Add($Control, 1, $row)
}

function Add-KioskGuiRow {
    param(
        [Windows.Forms.TableLayoutPanel] $Root,
        [Windows.Forms.Control] $Control
    )
    $row = $Root.RowCount
    $Root.RowCount++
    [void] $Root.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::AutoSize))
    $Root.Controls.Add($Control, 0, $row)
}

function New-KioskGuiGroup {
    param([string] $Title)
    $group = [Windows.Forms.GroupBox]::new()
    $group.Text = $Title
    $group.AutoSize = $true
    $group.AutoSizeMode = "GrowAndShrink"
    $group.Dock = "Top"
    $group.Padding = [Windows.Forms.Padding]::new(12, 8, 12, 12)
    $group.Margin = [Windows.Forms.Padding]::new(0, 0, 0, 16)

    $table = [Windows.Forms.TableLayoutPanel]::new()
    $table.AutoSize = $true
    $table.AutoSizeMode = "GrowAndShrink"
    $table.Dock = "Fill"
    $table.ColumnCount = 2
    [void] $table.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Absolute, 180))
    [void] $table.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent, 100))
    $group.Controls.Add($table)
    [pscustomobject]@{ Group = $group; Table = $table }
}

function New-KioskGuiRotation {
    $rotation = [Windows.Forms.ComboBox]::new()
    $rotation.DropDownStyle = "DropDownList"
    [void] $rotation.Items.AddRange(@(
        $script:SharedConfig.choices.rotation.none,
        $script:SharedConfig.choices.rotation.clockwise,
        $script:SharedConfig.choices.rotation.counterclockwise
    ))
    $rotation.SelectedIndex = 0
    $rotation
}

function Show-KioskGui {
    [Windows.Forms.Application]::EnableVisualStyles()
    $script:SharedConfig = Get-KioskSharedConfig
    $displays = @(Get-KioskDisplays)
    if ($displays.Count -eq 0) {
        [void] [Windows.Forms.MessageBox]::Show(
            "No active displays were detected. Nothing was changed.",
            "Kiosk setup", "OK", "Warning"
        )
        return 0
    }
    $multiple = $displays.Count -gt 1

    $form = [Windows.Forms.Form]::new()
    $form.Text = "Kiosk setup"
    $form.StartPosition = "CenterScreen"
    $form.ClientSize = [Drawing.Size]::new(720, 720)
    $form.MinimumSize = [Drawing.Size]::new(620, 620)
    $form.Font = [Drawing.SystemFonts]::MessageBoxFont
    $form.AutoScaleMode = "Font"

    $scroll = [Windows.Forms.Panel]::new()
    $scroll.Dock = "Fill"
    $scroll.AutoScroll = $true
    $scroll.Padding = [Windows.Forms.Padding]::new(24)
    $form.Controls.Add($scroll)

    $root = [Windows.Forms.TableLayoutPanel]::new()
    $root.Dock = "Top"
    $root.AutoSize = $true
    $root.AutoSizeMode = "GrowAndShrink"
    $root.ColumnCount = 1
    $root.RowCount = 0
    $root.GrowStyle = "AddRows"
    [void] $root.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent, 100))
    $scroll.Controls.Add($root)

    $title = [Windows.Forms.Label]::new()
    $title.Text = "Configure this Windows kiosk"
    $title.Font = [Drawing.Font]::new($form.Font.FontFamily, 16, [Drawing.FontStyle]::Bold)
    $title.AutoSize = $true
    $title.Margin = [Windows.Forms.Padding]::new(0, 0, 0, 6)
    Add-KioskGuiRow $root $title

    $intro = [Windows.Forms.Label]::new()
    $intro.Text = if ($multiple) {
        "$($displays.Count) displays detected. Each one plays its own looping video and they start together. Review the settings, then select Configure kiosk."
    } else {
        "Review the settings, then select Configure kiosk."
    }
    $intro.AutoSize = $true
    $intro.MaximumSize = [Drawing.Size]::new(640, 0)
    $intro.Margin = [Windows.Forms.Padding]::new(0, 0, 0, 20)
    Add-KioskGuiRow $root $intro

    $sections = @()
    if ($multiple) {
        $tabs = [Windows.Forms.TabControl]::new()
        $tabs.Anchor = "Top, Left, Right"
        $tabs.Height = 190
        $tabs.Margin = [Windows.Forms.Padding]::new(0, 0, 0, 16)
        foreach ($display in $displays) {
            $page = [Windows.Forms.TabPage]::new()
            $page.Text = "Display $($display.Number)"
            $page.Padding = [Windows.Forms.Padding]::new(12)
            $page.UseVisualStyleBackColor = $true
            $group = New-KioskGuiGroup (Format-KioskDisplay $display)
            $rotationBox = New-KioskGuiRotation
            Add-KioskGuiField $group.Table "Rotation:" $rotationBox
            $sourceBox = [Windows.Forms.TextBox]::new()
            $sourceBox.AccessibleDescription = "Dropbox shared video link for display $($display.Number)"
            Add-KioskGuiField $group.Table "Dropbox link:" $sourceBox
            $page.Controls.Add($group.Group)
            [void] $tabs.TabPages.Add($page)
            $sections += [pscustomobject]@{
                Display = $display; Rotation = $rotationBox; Type = $null; FixedType = "video"; Source = $sourceBox
            }
        }
        Add-KioskGuiRow $root $tabs
    } else {
        $displayGroup = New-KioskGuiGroup "Display"
        $displayBox = [Windows.Forms.TextBox]::new()
        $displayBox.ReadOnly = $true
        $displayBox.Text = Format-KioskDisplay $displays[0]
        Add-KioskGuiField $displayGroup.Table "Active display:" $displayBox
        $rotationBox = New-KioskGuiRotation
        Add-KioskGuiField $displayGroup.Table "Rotation:" $rotationBox
        Add-KioskGuiRow $root $displayGroup.Group

        $contentGroup = New-KioskGuiGroup "Kiosk content"
        $projectType = [Windows.Forms.ComboBox]::new()
        $projectType.DropDownStyle = "DropDownList"
        [void] $projectType.Items.AddRange(@(
            $script:SharedConfig.choices.project.webapp,
            $script:SharedConfig.choices.project.video
        ))
        $projectType.SelectedIndex = 0
        Add-KioskGuiField $contentGroup.Table "Type:" $projectType
        $sourceBox = [Windows.Forms.TextBox]::new()
        Add-KioskGuiField $contentGroup.Table "S3 ZIP path:" $sourceBox
        $sourceLabel = $contentGroup.Table.GetControlFromPosition(0, 1)
        $sourceBox.AccessibleDescription = "Example: $($script:SharedConfig.webappPathExample)"
        Add-KioskGuiRow $root $contentGroup.Group
        $sections += [pscustomobject]@{
            Display = $displays[0]; Rotation = $rotationBox; Type = $projectType; FixedType = ""; Source = $sourceBox
        }
    }

    $audioGroup = New-KioskGuiGroup "Audio"
    $audioDevices = @()
    $audioSource = [Windows.Forms.ComboBox]::new()
    $audioSource.DropDownStyle = "DropDownList"
    if ($multiple) {
        foreach ($display in $displays) {
            [void] $audioSource.Items.Add("Display $($display.Number) ($($display.DeviceName))")
        }
        $audioDevices = @(Get-KioskAudioDevices)
    } else {
        [void] $audioSource.Items.Add("Display 1 - the only screen")
    }
    $audioSource.SelectedIndex = 0
    $audioSource.Enabled = $multiple
    Add-KioskGuiField $audioGroup.Table "Audio from:" $audioSource

    $audioOutput = [Windows.Forms.ComboBox]::new()
    $audioOutput.DropDownStyle = "DropDownList"
    [void] $audioOutput.Items.Add("Default output - whatever is available when it plays")
    foreach ($device in $audioDevices) { [void] $audioOutput.Items.Add($device.Name) }
    $audioOutput.SelectedIndex = 0
    $audioOutput.Enabled = $multiple
    Add-KioskGuiField $audioGroup.Table "Output:" $audioOutput

    $audioNote = [Windows.Forms.Label]::new()
    $audioNote.Text = if ($multiple) {
        "Only one screen plays sound; the others are muted. If just one video turns out to carry an audio track, setup uses that one."
    } else {
        "The only video plays its own sound through the output available when it plays."
    }
    $audioNote.AutoSize = $true
    $audioNote.MaximumSize = [Drawing.Size]::new(480, 0)
    $audioNote.Margin = [Windows.Forms.Padding]::new(0, 8, 0, 0)
    $audioNoteRow = $audioGroup.Table.RowCount
    $audioGroup.Table.RowCount++
    [void] $audioGroup.Table.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::AutoSize))
    $audioGroup.Table.Controls.Add($audioNote, 0, $audioNoteRow)
    $audioGroup.Table.SetColumnSpan($audioNote, 2)
    Add-KioskGuiRow $root $audioGroup.Group

    $accountGroup = New-KioskGuiGroup "Access"
    $windowsPassword = [Windows.Forms.TextBox]::new()
    $windowsPassword.UseSystemPasswordChar = $true
    $windowsPassword.AccessibleDescription = "Use the Windows account password, not the PIN. Leave empty only for a passwordless local account."
    Add-KioskGuiField $accountGroup.Table "Windows password (not PIN):" $windowsPassword
    $rustDeskPassword = [Windows.Forms.TextBox]::new()
    $rustDeskPassword.UseSystemPasswordChar = $true
    Add-KioskGuiField $accountGroup.Table "RustDesk password:" $rustDeskPassword
    Add-KioskGuiRow $root $accountGroup.Group

    $registrationGroup = New-KioskGuiGroup "Registration"
    $registerTotem = [Windows.Forms.CheckBox]::new()
    $registerTotem.Text = "Register this totem"
    $registerTotem.Checked = $true
    $registerTotem.AutoSize = $true
    $registerTotem.Margin = [Windows.Forms.Padding]::new(0, 4, 0, 8)
    $registrationGroup.Table.RowCount++
    $registrationGroup.Table.Controls.Add($registerTotem, 0, 0)
    $registrationGroup.Table.SetColumnSpan($registerTotem, 2)
    $totemName = [Windows.Forms.TextBox]::new()
    Add-KioskGuiField $registrationGroup.Table "Name:" $totemName
    $totemDescription = [Windows.Forms.TextBox]::new()
    Add-KioskGuiField $registrationGroup.Table "Description:" $totemDescription
    $totemLocation = [Windows.Forms.TextBox]::new()
    Add-KioskGuiField $registrationGroup.Table "Location:" $totemLocation
    Add-KioskGuiRow $root $registrationGroup.Group

    $finishGroup = New-KioskGuiGroup "After setup"
    $finalAction = [Windows.Forms.ComboBox]::new()
    $finalAction.DropDownStyle = "DropDownList"
    $lastChoice = if ($multiple) { "Do nothing" } else { "Keep the app server running" }
    [void] $finalAction.Items.AddRange(@("Launch now", "Reboot", $lastChoice))
    $finalAction.SelectedIndex = 0
    Add-KioskGuiField $finishGroup.Table "Next action:" $finalAction
    Add-KioskGuiRow $root $finishGroup.Group

    $status = [Windows.Forms.TextBox]::new()
    $status.Multiline = $true
    $status.ReadOnly = $true
    $status.ScrollBars = "Vertical"
    $status.Height = 130
    $status.Anchor = "Top, Left, Right"
    $status.AccessibleName = "Setup progress"
    $status.Text = "Ready."
    $status.Margin = [Windows.Forms.Padding]::new(0, 0, 0, 12)
    Add-KioskGuiRow $root $status

    $buttons = [Windows.Forms.FlowLayoutPanel]::new()
    $buttons.FlowDirection = "RightToLeft"
    $buttons.WrapContents = $false
    $buttons.AutoSize = $true
    $buttons.AutoSizeMode = "GrowAndShrink"
    $buttons.Dock = "Top"
    $buttons.Margin = [Windows.Forms.Padding]::new(0, 4, 0, 24)

    $apply = [Windows.Forms.Button]::new()
    $apply.Text = "Configure kiosk"
    $apply.AutoSize = $true
    $apply.MinimumSize = [Drawing.Size]::new(140, 38)
    $apply.Margin = [Windows.Forms.Padding]::new(8, 0, 0, 0)
    $buttons.Controls.Add($apply)

    $remove = [Windows.Forms.Button]::new()
    $remove.Text = "Remove kiosk setup"
    $remove.AutoSize = $true
    $remove.MinimumSize = [Drawing.Size]::new(140, 38)
    $remove.Margin = [Windows.Forms.Padding]::new(8, 0, 0, 0)
    $remove.AccessibleDescription = "Undo the kiosk configuration on this PC."
    $buttons.Controls.Add($remove)

    Add-KioskGuiRow $root $buttons
    $form.AcceptButton = $apply

    if (-not $multiple) {
        $singleType = $sections[0].Type
        $singleSource = $sections[0].Source
        $singleType.Add_SelectedIndexChanged({
            if ($singleType.SelectedIndex -eq 0) {
                $sourceLabel.Text = "S3 ZIP path:"
                $singleSource.AccessibleName = "S3 ZIP path"
                $singleSource.AccessibleDescription = "Example: $($script:SharedConfig.webappPathExample)"
                $finalAction.Items[2] = "Keep the app server running"
                $audioSource.Items[0] = "Webapp on display 1"
                $audioNote.Text = "The webapp plays its own sound through the output available when it plays."
            } else {
                $sourceLabel.Text = "Dropbox link:"
                $singleSource.AccessibleName = "Dropbox link"
                $singleSource.AccessibleDescription = "Dropbox shared video link"
                $finalAction.Items[2] = "Do nothing"
                $audioSource.Items[0] = "Display 1 - the only screen"
                $audioNote.Text = "The only video plays its own sound through the output available when it plays."
            }
        })
    }

    $registerTotem.Add_CheckedChanged({
        foreach ($control in @($totemName, $totemDescription, $totemLocation)) {
            $control.Enabled = $registerTotem.Checked
        }
    })

    $timer = [Windows.Forms.Timer]::new()
    $timer.Interval = 300
    $timer.Add_Tick({
        if ($script:GuiStdout -and (Test-Path $script:GuiStdout)) {
            $text = Get-Content -Raw $script:GuiStdout -ErrorAction SilentlyContinue
            if ($text) { $status.Text = $text; $status.SelectionStart = $status.TextLength; $status.ScrollToCaret() }
        }
        if ($script:GuiProcess -and $script:GuiProcess.HasExited) {
            $timer.Stop()
            $script:GuiProcess.WaitForExit()
            $errorText = if (Test-Path $script:GuiStderr) { Get-Content -Raw $script:GuiStderr } else { "" }
            $what = if ($script:GuiOperation -eq "cleanup") { "Cleanup" } else { "Setup" }
            if ($script:GuiProcess.ExitCode -eq 0) {
                $status.AppendText("`r`n$what completed.")
                [void] [Windows.Forms.MessageBox]::Show("$what completed.", "Kiosk setup", "OK", "Information")
            } else {
                $status.AppendText("`r`nERROR: $errorText")
                [void] [Windows.Forms.MessageBox]::Show("$what failed. $errorText", "Kiosk setup", "OK", "Error")
            }
            Remove-Item -Recurse -Force $script:GuiWork -ErrorAction SilentlyContinue
            $script:GuiProcess = $null
            $apply.Enabled = $true
            $remove.Enabled = $true
        }
    })

    $apply.Add_Click({
        $planned = @($sections | ForEach-Object {
            $type = if ($_.Type) { @("webapp", "video")[$_.Type.SelectedIndex] } else { $_.FixedType }
            New-KioskDisplayPlan $_.Display `
                -Rotation @("none", "clockwise", "counterclockwise")[$_.Rotation.SelectedIndex] `
                -Type $type -Source $_.Source.Text.Trim()
        })
        $audioNumber = 0
        $audioId = ""
        $audioName = ""
        $videoPlanned = @($planned | Where-Object { $_.Type -eq "video" })
        if ($videoPlanned.Count -gt 0) {
            if ($multiple) {
                $audioNumber = $displays[$audioSource.SelectedIndex].Number
                if ($audioOutput.SelectedIndex -gt 0) {
                    $audioId = $audioDevices[$audioOutput.SelectedIndex - 1].Id
                    $audioName = $audioDevices[$audioOutput.SelectedIndex - 1].Name
                }
            } else {
                $audioNumber = $videoPlanned[0].Number
            }
        }

        $plan = New-KioskPlan -Displays $planned `
            -AudioDisplay $audioNumber -AudioDevice $audioId -AudioDeviceName $audioName `
            -WindowsPassword $windowsPassword.Text -RustDeskPassword $rustDeskPassword.Text `
            -Register $registerTotem.Checked -TotemName $totemName.Text `
            -TotemDescription $totemDescription.Text -TotemLocation $totemLocation.Text `
            -FinalAction @("launch", "reboot", "nothing")[$finalAction.SelectedIndex]

        $validationError = Test-KioskPlan $plan
        if ($validationError) {
            $status.Text = $validationError
            [void] [Windows.Forms.MessageBox]::Show($validationError, "Check the settings", "OK", "Warning")
            return
        }

        $apply.Enabled = $false
        $status.Text = "Starting setup..."
        $script:GuiWork = Join-Path ([IO.Path]::GetTempPath()) ("pi-kiosk-gui-" + [guid]::NewGuid())
        New-Item -ItemType Directory -Path $script:GuiWork | Out-Null
        $configPath = Join-Path $script:GuiWork "setup.json"
        @{
            windowsPassword = Protect-KioskGuiSecret $windowsPassword.Text
            rustDeskPassword = Protect-KioskGuiSecret $rustDeskPassword.Text
            registerTotem = $plan.Register
            totemName = $plan.TotemName
            totemDescription = $plan.TotemDescription
            totemLocation = $plan.TotemLocation
            finalAction = $plan.FinalAction
            audioDisplay = $plan.AudioDisplay
            audioDevice = $plan.AudioDevice
            audioDeviceName = $plan.AudioDeviceName
            displays = @(@($plan.Displays) | ForEach-Object {
                @{ number = $_.Number; deviceName = $_.DeviceName; rotation = $_.Rotation; type = $_.Type; source = $_.Source }
            })
        } | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $configPath
        $script:GuiOperation = "setup"
        $script:GuiStdout = Join-Path $script:GuiWork "setup.log"
        $script:GuiStderr = Join-Path $script:GuiWork "error.log"
        $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ApplyConfig `"$configPath`""
        $script:GuiProcess = Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput $script:GuiStdout -RedirectStandardError $script:GuiStderr -PassThru
        $timer.Start()
    })

    $remove.Add_Click({
        $warning = "This undoes the kiosk configuration on this PC: startup entry, status reporting, " +
            "Windows autologin, the downloaded video and webapp files, the local web server reservation, " +
            "and it turns every display back to 0 degrees.`r`n`r`n" +
            "RustDesk, VLC, the power settings and the remote registration are left alone.`r`n`r`n" +
            "Continue?"
        $answer = [Windows.Forms.MessageBox]::Show($warning, "Remove kiosk setup", "YesNo", "Warning", "Button2")
        if ($answer -ne "Yes") { return }

        $apply.Enabled = $false
        $remove.Enabled = $false
        $status.Text = "Removing the kiosk configuration..."
        $script:GuiWork = Join-Path ([IO.Path]::GetTempPath()) ("pi-kiosk-gui-" + [guid]::NewGuid())
        New-Item -ItemType Directory -Path $script:GuiWork | Out-Null
        $script:GuiOperation = "cleanup"
        $script:GuiStdout = Join-Path $script:GuiWork "setup.log"
        $script:GuiStderr = Join-Path $script:GuiWork "error.log"
        $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Cleanup"
        $script:GuiProcess = Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput $script:GuiStdout -RedirectStandardError $script:GuiStderr -PassThru
        $timer.Start()
    })

    $form.Add_FormClosing({
        param($sender, $eventArgs)
        if ($script:GuiProcess -and -not $script:GuiProcess.HasExited) {
            $eventArgs.Cancel = $true
            [void] [Windows.Forms.MessageBox]::Show("Work is still running. Wait for it to finish before closing this window.", "Kiosk setup", "OK", "Information")
        }
    })

    $script:GuiProcess = $null
    $script:GuiOperation = "setup"
    $script:GuiWork = $null
    $script:GuiStdout = $null
    $script:GuiStderr = $null
    [Windows.Forms.Application]::Run($form)
    0
}

function Invoke-KioskGuiMain {
    if (-not (Test-KioskAdministrator)) {
        $arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`""
        if ($ApplyConfig) { $arguments += " -ApplyConfig `"$ApplyConfig`"" }
        if ($Cleanup) { $arguments += " -Cleanup" }
        try {
            $elevated = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -PassThru
            $elevated.WaitForExit()
            return $elevated.ExitCode
        } catch {
            [void] [Windows.Forms.MessageBox]::Show("Administrator access was not granted. Nothing was changed.", "Kiosk setup", "OK", "Warning")
            return 1
        }
    }
    if ($Cleanup) { return Invoke-KioskGuiCleanup }
    if ($ApplyConfig) { return Invoke-KioskGuiSetup $ApplyConfig }
    try { Show-KioskGui }
    catch {
        Add-Type -AssemblyName System.Windows.Forms
        [void] [Windows.Forms.MessageBox]::Show($_.Exception.Message, "Kiosk setup", "OK", "Error")
        1
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    exit (Invoke-KioskGuiMain)
}

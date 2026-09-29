param([string] $ApplyConfig = "")

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

function Get-KioskGuiValidationError {
    param([object] $Values)
    if ([string]::IsNullOrWhiteSpace($Values.RustDeskPassword)) {
        return "Enter a RustDesk password."
    }
    try {
        if ($Values.ProjectType -eq "webapp") { [void] (Normalize-WebAppSource $Values.Source) }
        elseif ($Values.ProjectType -eq "video") { [void] (Normalize-VideoSource $Values.Source) }
        else { return "Choose a kiosk type." }
    } catch { return $_.Exception.Message }
    if ($Values.RegisterTotem -and [string]::IsNullOrWhiteSpace($Values.TotemName)) {
        return "Enter a totem name or turn off registration."
    }
    $null
}

function Invoke-KioskGuiSetup {
    param([Parameter(Mandatory = $true)][string] $ConfigPath)
    try {
        if (-not (Test-KioskAdministrator)) { throw "Administrator access is required." }
        $script:SharedConfig = Get-KioskSharedConfig
        $config = Get-Content -Raw $ConfigPath | ConvertFrom-Json
        $values = [pscustomobject]@{
            Rotation = [string] $config.rotation
            WindowsPassword = Unprotect-KioskGuiSecret ([string] $config.windowsPassword)
            RustDeskPassword = Unprotect-KioskGuiSecret ([string] $config.rustDeskPassword)
            ProjectType = [string] $config.projectType
            Source = [string] $config.source
            RegisterTotem = [bool] $config.registerTotem
            TotemName = [string] $config.totemName
            TotemDescription = [string] $config.totemDescription
            TotemLocation = [string] $config.totemLocation
            FinalAction = [string] $config.finalAction
        }
        $validationError = Get-KioskGuiValidationError $values
        if ($validationError) { throw $validationError }
        if ($values.Rotation -notin @("none", "clockwise", "counterclockwise")) { throw "Choose a screen rotation." }
        if ($values.FinalAction -notin @("launch", "reboot", "nothing")) { throw "Choose what to do after setup." }

        $displays = @(Get-KioskDisplays)
        if ($displays.Count -ne 1) { throw "This version requires exactly one active display. Nothing was changed." }
        $sourceUrl = if ($values.ProjectType -eq "webapp") {
            Normalize-WebAppSource $values.Source
        } else {
            Normalize-VideoSource $values.Source
        }

        Set-KioskRotation $displays[0] $values.Rotation
        Set-KioskNoSleep
        Enable-KioskAutologon -Password $values.WindowsPassword
        [void] (Install-KioskRustDesk $values.RustDeskPassword)
        $kiosk = if ($values.ProjectType -eq "webapp") {
            Install-KioskWebApp $sourceUrl
        } else {
            Install-KioskVideo $sourceUrl
        }
        if ($values.RegisterTotem) {
            Register-KioskTotem -TotemType $kiosk.Type -Name $values.TotemName -Description $values.TotemDescription -Location $values.TotemLocation
        } else {
            Write-KioskDone "skipped totem registration."
        }
        Show-KioskSummary
        Invoke-KioskFinalAction $kiosk -Action $values.FinalAction
        return 0
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        return 1
    } finally {
        Remove-Item -Force $ConfigPath -ErrorAction SilentlyContinue
    }
}

function Add-KioskGuiField {
    param(
        [Windows.Forms.TableLayoutPanel] $Table,
        [string] $Text,
        [Windows.Forms.Control] $Control
    )
    $row = $Table.RowCount
    $Table.RowCount++
    $Table.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::AutoSize))
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
    $table.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Absolute, 180))
    $table.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent, 100))
    $group.Controls.Add($table)
    [pscustomobject]@{ Group = $group; Table = $table }
}

function Show-KioskGui {
    [Windows.Forms.Application]::EnableVisualStyles()
    $script:SharedConfig = Get-KioskSharedConfig
    $displays = @(Get-KioskDisplays)
    if ($displays.Count -ne 1) {
        [void] [Windows.Forms.MessageBox]::Show(
            "This version requires exactly one active display. Nothing was changed.",
            "Kiosk setup", "OK", "Warning"
        )
        return 0
    }

    $form = [Windows.Forms.Form]::new()
    $form.Text = "Kiosk setup"
    $form.StartPosition = "CenterScreen"
    $form.ClientSize = [Drawing.Size]::new(720, 680)
    $form.MinimumSize = [Drawing.Size]::new(620, 620)
    $form.Font = [Drawing.SystemFonts]::MessageBoxFont
    $form.AutoScaleMode = "Font"

    $root = [Windows.Forms.TableLayoutPanel]::new()
    $root.Dock = "Fill"
    $root.AutoScroll = $true
    $root.ColumnCount = 1
    $root.Padding = [Windows.Forms.Padding]::new(24)
    $root.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent, 100))
    $form.Controls.Add($root)

    $title = [Windows.Forms.Label]::new()
    $title.Text = "Configure this Windows kiosk"
    $title.Font = [Drawing.Font]::new($form.Font.FontFamily, 16, [Drawing.FontStyle]::Bold)
    $title.AutoSize = $true
    $title.Margin = [Windows.Forms.Padding]::new(0, 0, 0, 6)
    $root.Controls.Add($title)

    $intro = [Windows.Forms.Label]::new()
    $intro.Text = "Review the settings, then select Configure kiosk."
    $intro.AutoSize = $true
    $intro.Margin = [Windows.Forms.Padding]::new(0, 0, 0, 20)
    $root.Controls.Add($intro)

    $displayGroup = New-KioskGuiGroup "Display"
    $display = [Windows.Forms.TextBox]::new()
    $display.ReadOnly = $true
    $display.Text = Format-KioskDisplay $displays[0]
    Add-KioskGuiField $displayGroup.Table "Active display:" $display
    $rotation = [Windows.Forms.ComboBox]::new()
    $rotation.DropDownStyle = "DropDownList"
    [void] $rotation.Items.AddRange(@(
        $script:SharedConfig.choices.rotation.none,
        $script:SharedConfig.choices.rotation.clockwise,
        $script:SharedConfig.choices.rotation.counterclockwise
    ))
    $rotation.SelectedIndex = 0
    Add-KioskGuiField $displayGroup.Table "Rotation:" $rotation
    $root.Controls.Add($displayGroup.Group)

    $accountGroup = New-KioskGuiGroup "Access"
    $windowsPassword = [Windows.Forms.TextBox]::new()
    $windowsPassword.UseSystemPasswordChar = $true
    $windowsPassword.AccessibleDescription = "Use the Windows account password, not the PIN. Leave empty only for a passwordless local account."
    Add-KioskGuiField $accountGroup.Table "Windows password (not PIN):" $windowsPassword
    $rustDeskPassword = [Windows.Forms.TextBox]::new()
    $rustDeskPassword.UseSystemPasswordChar = $true
    Add-KioskGuiField $accountGroup.Table "RustDesk password:" $rustDeskPassword
    $root.Controls.Add($accountGroup.Group)

    $contentGroup = New-KioskGuiGroup "Kiosk content"
    $projectType = [Windows.Forms.ComboBox]::new()
    $projectType.DropDownStyle = "DropDownList"
    [void] $projectType.Items.AddRange(@(
        $script:SharedConfig.choices.project.webapp,
        $script:SharedConfig.choices.project.video
    ))
    $projectType.SelectedIndex = 0
    Add-KioskGuiField $contentGroup.Table "Type:" $projectType
    $source = [Windows.Forms.TextBox]::new()
    Add-KioskGuiField $contentGroup.Table "S3 ZIP path:" $source
    $sourceLabel = $contentGroup.Table.GetControlFromPosition(0, 1)
    $source.AccessibleDescription = "Example: $($script:SharedConfig.webappPathExample)"
    $root.Controls.Add($contentGroup.Group)

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
    $root.Controls.Add($registrationGroup.Group)

    $finishGroup = New-KioskGuiGroup "After setup"
    $finalAction = [Windows.Forms.ComboBox]::new()
    $finalAction.DropDownStyle = "DropDownList"
    [void] $finalAction.Items.AddRange(@("Launch now", "Reboot", "Keep the app server running"))
    $finalAction.SelectedIndex = 0
    Add-KioskGuiField $finishGroup.Table "Next action:" $finalAction
    $root.Controls.Add($finishGroup.Group)

    $status = [Windows.Forms.TextBox]::new()
    $status.Multiline = $true
    $status.ReadOnly = $true
    $status.ScrollBars = "Vertical"
    $status.Height = 130
    $status.Dock = "Top"
    $status.AccessibleName = "Setup progress"
    $status.Text = "Ready."
    $status.Margin = [Windows.Forms.Padding]::new(0, 0, 0, 12)
    $root.Controls.Add($status)

    $apply = [Windows.Forms.Button]::new()
    $apply.Text = "Configure kiosk"
    $apply.AutoSize = $true
    $apply.MinimumSize = [Drawing.Size]::new(140, 38)
    $apply.Anchor = "Right"
    $root.Controls.Add($apply)
    $form.AcceptButton = $apply

    $projectType.Add_SelectedIndexChanged({
        if ($projectType.SelectedIndex -eq 0) {
            $sourceLabel.Text = "S3 ZIP path:"
            $source.AccessibleName = "S3 ZIP path"
            $source.AccessibleDescription = "Example: $($script:SharedConfig.webappPathExample)"
            $finalAction.Items[2] = "Keep the app server running"
        } else {
            $sourceLabel.Text = "Dropbox link:"
            $source.AccessibleName = "Dropbox link"
            $source.AccessibleDescription = "Dropbox shared video link"
            $finalAction.Items[2] = "Do nothing"
        }
    })

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
            if ($script:GuiProcess.ExitCode -eq 0) {
                $status.AppendText("`r`nSetup completed.")
                [void] [Windows.Forms.MessageBox]::Show("Kiosk setup completed.", "Kiosk setup", "OK", "Information")
            } else {
                $status.AppendText("`r`nERROR: $errorText")
                [void] [Windows.Forms.MessageBox]::Show("Setup failed. $errorText", "Kiosk setup", "OK", "Error")
            }
            Remove-Item -Recurse -Force $script:GuiWork -ErrorAction SilentlyContinue
            $script:GuiProcess = $null
            $apply.Enabled = $true
        }
    })

    $apply.Add_Click({
        $values = [pscustomobject]@{
            Rotation = @("none", "clockwise", "counterclockwise")[$rotation.SelectedIndex]
            WindowsPassword = $windowsPassword.Text
            RustDeskPassword = $rustDeskPassword.Text
            ProjectType = @("webapp", "video")[$projectType.SelectedIndex]
            Source = $source.Text
            RegisterTotem = $registerTotem.Checked
            TotemName = $totemName.Text
            TotemDescription = $totemDescription.Text
            TotemLocation = $totemLocation.Text
            FinalAction = @("launch", "reboot", "nothing")[$finalAction.SelectedIndex]
        }
        $validationError = Get-KioskGuiValidationError $values
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
            rotation = $values.Rotation
            windowsPassword = Protect-KioskGuiSecret $values.WindowsPassword
            rustDeskPassword = Protect-KioskGuiSecret $values.RustDeskPassword
            projectType = $values.ProjectType
            source = $values.Source
            registerTotem = $values.RegisterTotem
            totemName = $values.TotemName
            totemDescription = $values.TotemDescription
            totemLocation = $values.TotemLocation
            finalAction = $values.FinalAction
        } | ConvertTo-Json | Set-Content -Encoding UTF8 $configPath
        $script:GuiStdout = Join-Path $script:GuiWork "setup.log"
        $script:GuiStderr = Join-Path $script:GuiWork "error.log"
        $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ApplyConfig `"$configPath`""
        $script:GuiProcess = Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput $script:GuiStdout -RedirectStandardError $script:GuiStderr -PassThru
        $timer.Start()
    })

    $form.Add_FormClosing({
        param($sender, $eventArgs)
        if ($script:GuiProcess -and -not $script:GuiProcess.HasExited) {
            $eventArgs.Cancel = $true
            [void] [Windows.Forms.MessageBox]::Show("Setup is still running. Wait for it to finish before closing this window.", "Kiosk setup", "OK", "Information")
        }
    })

    $script:GuiProcess = $null
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
        try {
            $elevated = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -PassThru
            $elevated.WaitForExit()
            return $elevated.ExitCode
        } catch {
            [void] [Windows.Forms.MessageBox]::Show("Administrator access was not granted. Nothing was changed.", "Kiosk setup", "OK", "Warning")
            return 1
        }
    }
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

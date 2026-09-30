from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "windows"


def read(*parts: str) -> str:
    return WINDOWS.joinpath(*parts).read_text(encoding="utf-8")


class WindowsEntrypointTests(unittest.TestCase):
    def test_cmd_entrypoint_runs_the_powershell_wizard(self):
        script = (WINDOWS / "kiosk.cmd").read_text(encoding="utf-8")

        self.assertIn("powershell.exe", script.lower())
        self.assertIn('"%~dp0kiosk.ps1"', script)

    def test_successful_setup_does_not_show_a_redundant_modal(self):
        gui = read("kiosk-gui.ps1")
        success = gui[gui.index('if (Test-KioskGuiOperationSucceeded $script:GuiOperation'):]
        success = success[:success.index('if ($script:GuiProcess.ExitCode -eq 0)')]

        self.assertIn('$status.AppendText("`r`n$what completed.")', success)
        self.assertIn('if ($script:GuiOperation -ne "setup") {', success)
        self.assertLess(success.index('if ($script:GuiOperation -ne "setup") {'), success.index('MessageBox]::Show("$what completed.'))
        self.assertIn('MessageBox]::Show("$what failed.', gui)

    def test_gui_keeps_diagnostics_when_worker_fails_without_stderr(self):
        gui = read("kiosk-gui.ps1")

        self.assertIn('if (-not $errorText)', gui)
        self.assertIn('Logs saved in $script:GuiWork', gui)
        self.assertIn('if ($script:GuiProcess.ExitCode -eq 0)', gui)
        self.assertIn('"setup-complete"', gui)
        self.assertIn('function Test-KioskGuiOperationSucceeded', gui)
        self.assertIn('if (Test-KioskGuiOperationSucceeded $script:GuiOperation', gui)

    def test_gui_restores_last_non_secret_answers_before_showing_the_form(self):
        gui = read("kiosk-gui.ps1")

        for name in ("Save-KioskGuiSettings", "Get-KioskGuiDefaults", "Get-KioskGuiDisplaySettings"):
            self.assertIn(f"function {name}", gui)
        self.assertIn("Save-KioskGuiSettings $plan", gui)
        self.assertIn("$defaults = Get-KioskGuiDefaults", gui)
        self.assertLess(gui.index("$defaults = Get-KioskGuiDefaults"), gui.index("[Windows.Forms.Application]::Run($form)"))
        self.assertLess(gui.index("Save-KioskGuiSettings $plan"), gui.index("$script:GuiProcess = Start-Process powershell.exe"))

    def test_rustdesk_password_requires_masked_confirmation_before_setup(self):
        gui = read("kiosk-gui.ps1")
        app = read("src", "app.ps1")
        ui = read("src", "ui.ps1")

        self.assertIn('$rustDeskConfirmation.UseSystemPasswordChar = $true', gui)
        self.assertIn('Test-KioskRustDeskConfirmation $rustDeskPassword.Text $rustDeskConfirmation.Text', gui)
        self.assertLess(gui.index('Test-KioskRustDeskConfirmation $rustDeskPassword.Text'), gui.index('Save-KioskGuiSettings $plan'))
        start = gui.index('$configPath = Join-Path $script:GuiWork "setup.json"')
        config = gui[start:gui.index('$script:GuiOperation = "setup"', start)]
        self.assertNotIn('rustDeskConfirmation', config)
        self.assertIn('Read-KioskConfirmedSecret $script:SharedConfig.prompts.rustdeskPassword', app)
        self.assertIn('function Read-KioskConfirmedSecret', ui)

    def test_rustdesk_service_starts_automatically_before_unattended_setup(self):
        rustdesk = read("src", "steps", "rustdesk.ps1")

        self.assertIn("Get-Service -Name RustDesk", rustdesk)
        self.assertIn("--install-service", rustdesk)
        self.assertIn("Set-Service -Name RustDesk -StartupType Automatic", rustdesk)
        self.assertIn("Start-Service -Name RustDesk", rustdesk)
        self.assertIn('Ensure-KioskRustDeskService $rustdesk', rustdesk)
        self.assertLess(rustdesk.index('Ensure-KioskRustDeskService $rustdesk'), rustdesk.index('--password $Password'))

    def test_portable_gui_uses_native_windows_controls(self):
        cmd = (WINDOWS / "kiosk-gui.cmd").read_text(encoding="utf-8")
        gui = read("kiosk-gui.ps1")

        self.assertIn("powershell.exe", cmd.lower())
        self.assertIn('"%~dp0kiosk-gui.ps1"', cmd)
        self.assertIn("System.Windows.Forms", gui)
        self.assertIn("[Windows.Forms.Application]::Run", gui)
        self.assertIn("UseSystemPasswordChar", gui)
        self.assertIn("ConvertFrom-SecureString", gui)
        self.assertIn("Invoke-KioskGuiSetup", gui)
        for function in ("New-KioskDisplayPlan", "New-KioskPlan", "Test-KioskPlan", "Invoke-KioskPlan"):
            self.assertIn(function, gui)

    def test_windows_reads_shared_and_state_files_as_utf8(self):
        offenders = []
        for script in sorted(WINDOWS.rglob("*.ps1")):
            for number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
                if "Get-Content" not in line or "ConvertFrom-Json" not in line:
                    continue
                if "-Encoding UTF8" not in line:
                    offenders.append(f"{script.relative_to(ROOT)}:{number}")
        self.assertEqual([], offenders)

    def test_rotation_labels_stay_ascii(self):
        shared = (ROOT / "shared" / "kiosk.json").read_text(encoding="utf-8")

        self.assertIn("90 deg", shared)
        self.assertNotIn("\u00b0", shared)

    def test_gui_scrolls_on_a_panel_with_auto_sized_rows(self):
        gui = read("kiosk-gui.ps1")

        self.assertIn("$scroll.AutoScroll = $true", gui)
        self.assertIn('$scroll.Dock = "Fill"', gui)
        self.assertIn('$root.Dock = "Top"', gui)
        self.assertIn("$root.AutoSize = $true", gui)
        self.assertNotIn("$root.AutoScroll", gui)
        self.assertNotIn("$root.Controls.Add(", gui)
        self.assertIn("function Add-KioskGuiRow", gui)

    def test_gui_never_leaks_collection_indexes_into_its_output(self):
        gui = read("kiosk-gui.ps1")

        leaking = [
            line.strip()
            for line in gui.splitlines()
            if re.search(r"\.(RowStyles|ColumnStyles|TabPages)\.Add\(", line)
            and not line.strip().startswith("[void]")
        ]
        self.assertEqual([], leaking)

    def test_remote_setup_opens_the_visual_wizard(self):
        setup = read("setup.ps1")

        self.assertIn("windows\\kiosk-gui.ps1", setup)

    def test_powershell_wizard_detects_all_active_displays(self):
        script = read("src", "steps", "rotation.ps1")

        self.assertIn("[System.Windows.Forms.Screen]::AllScreens", script)
        self.assertIn("Get-KioskDisplays", script)
        self.assertNotIn('\\\\.\\DISPLAY1"', script)

    def test_displays_keep_the_windows_enumeration_index(self):
        script = read("src", "steps", "rotation.ps1")

        self.assertIn("Index      = [int] $indexes[[string] $_.DeviceName]", script)

    def test_rotation_applies_every_display_in_one_commit(self):
        script = read("src", "steps", "rotation.ps1")

        self.assertIn("CDS_NORESET", script)
        self.assertIn("public static void Commit()", script)
        self.assertIn("function Set-KioskRotationPlan", script)
        self.assertLess(
            script.index("[KioskDisplay]::Rotate($display.DeviceName, $orientations[$display.Rotation], $false)"),
            script.index("[KioskDisplay]::Commit()"),
        )

    def test_the_wizard_applies_one_validated_plan(self):
        app = read("src", "app.ps1")

        self.assertIn("Invoke-KioskPlan", app)
        self.assertIn("Test-KioskPlan", app)
        self.assertNotIn("Test-KioskTouchscreen", app)
        for function in (
            "Set-KioskRotationPlan",
            "Set-KioskNoSleep",
            "Enable-KioskAutologon",
            "Install-KioskRustDesk",
            "Install-KioskWebApp",
            "Install-KioskVideo",
            "Write-KioskOrchestrator",
            "Register-KioskTotem",
        ):
            self.assertIn(function, app)
        self.assertLess(app.index("Test-KioskPlan"), app.index("Set-KioskRotationPlan"))

    def test_several_displays_are_video_only(self):
        plan = read("src", "plan.ps1")
        gui = read("kiosk-gui.ps1")

        self.assertIn("Multiple displays can only run video kiosks", plan)
        self.assertNotIn("requires exactly one active display", gui)

    def test_every_display_gets_its_own_video_directory(self):
        video = read("src", "steps", "video.ps1")

        self.assertIn('"video\\display-$($Display.Number)"', video)
        self.assertNotIn("Set-KioskStartup", video)

    def test_video_follows_physical_monitor_when_windows_display_numbers_change(self):
        rotation = read("src", "steps", "rotation.ps1")
        plan = read("src", "plan.ps1")
        startup = read("src", "steps", "startup.ps1")
        gui = read("kiosk-gui.ps1")

        self.assertIn("EDD_GET_DEVICE_INTERFACE_NAME", rotation)
        self.assertIn("MonitorId  =", plan)
        self.assertIn("monitorId = $_.MonitorId", startup)
        self.assertIn("Get-KioskMonitorId $Screens[$index].DeviceName", startup)
        self.assertIn('if ($matches.Count -eq 1)', startup)
        self.assertIn("$Display.MonitorId", gui)
        self.assertIn("monitorId = $_.MonitorId", gui)

    def test_startup_orchestrator_places_independent_repeating_players(self):
        startup = read("src", "steps", "startup.ps1")
        app = read("src", "app.ps1")

        self.assertIn("kiosk-start.ps1", startup)
        self.assertIn("--qt-fullscreen-screennumber", startup)
        self.assertIn("--repeat", startup)
        self.assertNotIn("--start-paused", startup)
        self.assertIn("Get-KioskScreenNumber", startup)
        self.assertIn("AllScreens", startup)
        self.assertIn("Set-KioskStartup $launcher", app)

    def test_setup_records_the_applied_plan(self):
        core = read("src", "core.ps1")
        app = read("src", "app.ps1")

        self.assertIn("kiosk-state.json", core)
        self.assertIn("function Save-KioskState", core)
        self.assertIn("Save-KioskState", app)

    def test_registration_reports_every_screen(self):
        registration = read("src", "steps", "registration.ps1")
        status = read("runtime", "totem-status.ps1")

        self.assertIn("screenCount = $screens.Count", registration)
        self.assertIn("screens = $screens", registration)
        self.assertIn("totem_id = $env:COMPUTERNAME", registration)
        self.assertIn("screens = $screens", status)
        self.assertIn("kiosk_running", status)
        self.assertIn("webapp_running", status)

    def test_totem_can_be_registered_on_its_own(self):
        entry = read("kiosk.ps1")
        app = read("src", "app.ps1")
        registration = read("src", "steps", "registration.ps1")
        gui = read("kiosk-gui.ps1")
        cmd = (WINDOWS / "kiosk.cmd").read_text(encoding="utf-8")

        self.assertIn("Invoke-KioskMain -Command $Command", entry)
        self.assertIn("%*", cmd)
        self.assertIn("register-totem", app)
        self.assertIn("Unknown command", app)
        self.assertIn("function Register-KioskTotemNow", registration)
        self.assertIn("function Get-KioskRegistrationDisplays", registration)
        self.assertIn("Get-KioskState", registration)
        self.assertIn("[string] $RegisterConfig", gui)
        self.assertIn("function Invoke-KioskGuiRegister", gui)
        self.assertIn('$registerOnly.Text = "Register totem"', gui)

    def test_standalone_registration_does_not_reconfigure_the_kiosk(self):
        registration = read("src", "steps", "registration.ps1")

        standalone = registration[registration.index("function Register-KioskTotemNow") :]
        standalone = standalone[: standalone.index("function Install-KioskStatusReporter")]
        for forbidden in ("Set-KioskRotation", "Install-KioskVideo", "Install-KioskWebApp", "Set-KioskStartup"):
            self.assertNotIn(forbidden, standalone)

    def test_gui_can_remove_the_kiosk_setup(self):
        gui = read("kiosk-gui.ps1")

        self.assertIn("[switch] $Cleanup", gui)
        self.assertIn("function Invoke-KioskGuiCleanup", gui)
        self.assertIn("Invoke-KioskCleanup", gui)
        self.assertIn('$remove.Text = "Remove kiosk setup"', gui)
        self.assertIn("$remove.Add_Click", gui)
        self.assertLess(gui.index("if ($Cleanup)"), gui.index("if ($ApplyConfig) { return Invoke-KioskGuiSetup"))

    def test_gui_asks_before_removing_the_kiosk_setup(self):
        gui = read("kiosk-gui.ps1")

        confirmation = gui[gui.index("$remove.Add_Click") : gui.index("$form.Add_FormClosing")]
        self.assertIn('"Remove kiosk setup", "YesNo", "Warning", "Button2"', confirmation)
        self.assertIn('if ($answer -ne "Yes") { return }', confirmation)
        self.assertLess(confirmation.index("MessageBox"), confirmation.index("Start-Process"))

    def test_audio_is_routed_to_one_screen_and_one_output(self):
        audio = read("src", "steps", "audio.ps1")
        plan = read("src", "plan.ps1")
        startup = read("src", "steps", "startup.ps1")
        app = read("src", "app.ps1")
        gui = read("kiosk-gui.ps1")

        self.assertIn("function Get-KioskAudioDevices", audio)
        self.assertIn("function Test-KioskVideoHasAudio", audio)
        self.assertIn("function Resolve-KioskAudioPlan", audio)
        self.assertIn("MMDevices\\Audio\\Render", audio)
        self.assertIn("System.Audio.ChannelCount", audio)
        self.assertIn("AudioDisplay", plan)
        self.assertIn("Choose which video the audio comes from.", plan)
        self.assertIn("--no-audio", startup)
        self.assertIn("--mmdevice-audio-device", startup)
        self.assertIn("Resolve-KioskAudioPlan", app)
        self.assertIn('New-KioskGuiGroup "Audio"', gui)
        self.assertLess(app.index("Resolve-KioskAudioPlan"), app.index("Write-KioskOrchestrator"))

    def test_audio_device_is_rechecked_before_playback(self):
        startup = read("src", "steps", "startup.ps1")

        self.assertIn("function Test-KioskAudioDevice", startup)
        self.assertIn("DeviceState", startup)
        self.assertLess(
            startup.index("function Test-KioskAudioDevice"),
            startup.index("function Start-KioskPlayer"),
        )

    def test_windows_steps_are_separate_files(self):
        steps = WINDOWS / "src" / "steps"
        for name in (
            "rotation",
            "nosleep",
            "autologin",
            "rustdesk",
            "webapp",
            "video",
            "audio",
            "startup",
            "registration",
            "final-action",
        ):
            self.assertTrue((steps / f"{name}.ps1").is_file(), name)
        self.assertFalse((steps / "touch.ps1").exists())
        self.assertTrue((WINDOWS / "src" / "plan.ps1").is_file())

    def test_autologon_supports_local_accounts_without_passwords(self):
        ui = read("src", "ui.ps1")
        autologon = read("src", "steps", "autologin.ps1")

        self.assertIn("[switch] $AllowEmpty", ui)
        self.assertIn("-AllowEmpty", autologon)
        self.assertIn("DefaultUserName", autologon)
        self.assertIn("DefaultDomainName", autologon)
        self.assertIn("DefaultPassword", autologon)
        self.assertIn("AutoAdminLogon", autologon)
        self.assertIn("$env:COMPUTERNAME", autologon)
        self.assertLess(
            autologon.index("if (-not $password)"),
            autologon.index("Downloading Microsoft Sysinternals Autologon"),
        )

    def test_cleanup_removes_owned_state_and_disables_autostart(self):
        cmd = WINDOWS / "cleanup.cmd"
        script = WINDOWS / "cleanup.ps1"
        bootstrap = WINDOWS / "cleanup-setup.ps1"

        self.assertTrue(cmd.is_file())
        self.assertTrue(script.is_file())
        self.assertTrue(bootstrap.is_file())
        cleanup = script.read_text(encoding="utf-8")
        for expected in (
            "pi-kiosk.cmd",
            "pi-kiosk-totem-status",
            'Join-Path $env:LOCALAPPDATA "pi-kiosk"',
            'Join-Path $env:ProgramData "pi-kiosk"',
            "kiosk-state.json",
            "http://127.0.0.1:$port/",
            "AutoAdminLogon",
            "DefaultPassword",
            "LsaStorePrivateData",
            "[KioskDisplay]::Rotate($display.DeviceName, 0)",
        ):
            self.assertIn(expected, cleanup)
        self.assertNotIn("powercfg", cleanup.lower())
        self.assertNotIn("winget uninstall", cleanup.lower())

    def test_remote_setup_downloads_one_repository_archive(self):
        setup = read("setup.ps1")

        self.assertIn("archive/refs/heads/master.zip", setup)
        self.assertIn("Expand-Archive", setup)
        self.assertIn("windows\\kiosk-gui.ps1", setup)

    def test_windows_has_a_dependency_free_display_test(self):
        script = read("tests", "run.ps1")

        self.assertIn("Get-KioskDisplays", script)
        self.assertIn("Normalize-WebAppSource", script)
        self.assertIn("Normalize-VideoSource", script)
        self.assertIn("Test-KioskPlan", script)
        self.assertIn("Write-KioskOrchestrator", script)
        self.assertNotIn("Invoke-Pester", script)

    def test_shared_service_configuration_is_outside_platform_folders(self):
        shared = ROOT / "shared" / "kiosk.json"
        self.assertTrue(shared.is_file())

        core = read("src", "core.ps1")
        final_action = read("src", "steps", "final-action.ps1")
        self.assertIn("shared\\kiosk.json", core)
        self.assertIn("$script:SharedConfig.prompts.videoNextAction", final_action)
        self.assertNotIn('"Choose what to do with the video now."', final_action)


if __name__ == "__main__":
    unittest.main()

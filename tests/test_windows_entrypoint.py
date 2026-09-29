from pathlib import Path
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

    def test_startup_orchestrator_places_and_synchronises_players(self):
        startup = read("src", "steps", "startup.ps1")
        app = read("src", "app.ps1")

        self.assertIn("kiosk-start.ps1", startup)
        self.assertIn("--qt-fullscreen-screennumber", startup)
        self.assertIn("--start-paused", startup)
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

    def test_windows_steps_are_separate_files(self):
        steps = WINDOWS / "src" / "steps"
        for name in (
            "rotation",
            "nosleep",
            "autologin",
            "rustdesk",
            "webapp",
            "video",
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

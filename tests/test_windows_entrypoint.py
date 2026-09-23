from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "windows"


class WindowsEntrypointTests(unittest.TestCase):
    def test_cmd_entrypoint_runs_the_powershell_wizard(self):
        script = (WINDOWS / "kiosk.cmd").read_text(encoding="utf-8")

        self.assertIn("powershell.exe", script.lower())
        self.assertIn('"%~dp0kiosk.ps1"', script)

    def test_powershell_wizard_detects_all_active_displays(self):
        script = (WINDOWS / "src" / "steps" / "rotation.ps1").read_text(encoding="utf-8")

        self.assertIn("[System.Windows.Forms.Screen]::AllScreens", script)
        self.assertIn("Get-KioskDisplays", script)
        self.assertNotIn('\\\\.\\DISPLAY1"', script)

    def test_single_display_wizard_is_an_explicit_list_of_steps(self):
        app = (WINDOWS / "src" / "app.ps1").read_text(encoding="utf-8")

        self.assertIn("Invoke-KioskWizard", app)
        for function in (
            "Set-KioskRotation",
            "Test-KioskTouchscreen",
            "Set-KioskNoSleep",
            "Enable-KioskAutologon",
            "Install-KioskRustDesk",
            "Install-KioskWebApp",
            "Install-KioskVideo",
            "Register-KioskTotem",
        ):
            self.assertIn(function, app)

    def test_windows_steps_are_separate_files(self):
        steps = WINDOWS / "src" / "steps"
        for name in (
            "rotation",
            "touch",
            "nosleep",
            "autologin",
            "rustdesk",
            "webapp",
            "video",
            "registration",
            "final-action",
        ):
            self.assertTrue((steps / f"{name}.ps1").is_file(), name)

    def test_remote_setup_downloads_one_repository_archive(self):
        setup = (WINDOWS / "setup.ps1").read_text(encoding="utf-8")

        self.assertIn("archive/refs/heads/master.zip", setup)
        self.assertIn("Expand-Archive", setup)
        self.assertIn("windows\\kiosk.ps1", setup)

    def test_windows_has_a_dependency_free_display_test(self):
        script = (WINDOWS / "tests" / "run.ps1").read_text(encoding="utf-8")

        self.assertIn("Get-KioskDisplays", script)
        self.assertIn("Normalize-WebAppSource", script)
        self.assertIn("Normalize-VideoSource", script)
        self.assertNotIn("Invoke-Pester", script)

    def test_shared_service_configuration_is_outside_platform_folders(self):
        shared = ROOT / "shared" / "kiosk.json"
        self.assertTrue(shared.is_file())

        core = (WINDOWS / "src" / "core.ps1").read_text(encoding="utf-8")
        final_action = (WINDOWS / "src" / "steps" / "final-action.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("shared\\kiosk.json", core)
        self.assertIn("$script:SharedConfig.prompts.videoNextAction", final_action)
        self.assertNotIn('"Choose what to do with the video now."', final_action)


if __name__ == "__main__":
    unittest.main()

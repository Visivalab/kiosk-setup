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
        script = (WINDOWS / "kiosk.ps1").read_text(encoding="utf-8")

        self.assertIn("[System.Windows.Forms.Screen]::AllScreens", script)
        self.assertIn("Get-KioskDisplays", script)
        self.assertNotIn('\\\\.\\DISPLAY1"', script)

    def test_windows_has_a_dependency_free_display_test(self):
        script = (WINDOWS / "tests" / "run.ps1").read_text(encoding="utf-8")

        self.assertIn("Get-KioskDisplays", script)
        self.assertNotIn("Invoke-Pester", script)


if __name__ == "__main__":
    unittest.main()

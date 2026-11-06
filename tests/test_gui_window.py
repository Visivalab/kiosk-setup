import json
import tempfile
import unittest
from pathlib import Path

from pi_kiosk import gui
from pi_kiosk.gui_launcher import run_gui
from tests.fakes import FakeHost


class GuiSettingsTests(unittest.TestCase):
    def test_saved_settings_never_contain_passwords(self):
        saved = gui.settings_to_save(
            {"rustdeskPassword": "a", "rustdeskPasswordConfirm": "a", "totemName": "Lobby"}
        )
        self.assertEqual(saved, {"totemName": "Lobby", "version": 1})

    def test_prefers_gui_settings_then_falls_back_to_kiosk_state(self):
        with tempfile.TemporaryDirectory() as home:
            state = {"displays": [{"output": "HDMI-A-1", "rotation": "clockwise"}], "skipRustDesk": True}
            defaults = gui.load_defaults(home, state)
            self.assertEqual(gui.display_defaults(defaults, "HDMI-A-1")["rotation"], "clockwise")
            self.assertTrue(defaults["skipRustDesk"])
            self.assertFalse(defaults["registerTotem"])

            gui.save_settings(home, {"displays": [{"output": "HDMI-A-1", "rotation": "none"}], "rustdeskPassword": "x"})
            defaults = gui.load_defaults(home, state)
            self.assertEqual(gui.display_defaults(defaults, "HDMI-A-1")["rotation"], "none")
            self.assertNotIn("x", Path(gui.settings_path(home)).read_text())

    def test_damaged_settings_do_not_block_the_window(self):
        with tempfile.TemporaryDirectory() as home:
            path = gui.settings_path(home)
            path.parent.mkdir(parents=True)
            path.write_text("{not json")
            self.assertIsNone(gui.load_defaults(home, None))

    def test_unknown_display_has_no_defaults(self):
        self.assertEqual(gui.display_defaults({"displays": [{"output": "HDMI-A-1"}]}, "HDMI-A-2"), {})

    def test_demo_hello_matches_the_real_hello_shape(self):
        from pi_kiosk.gui_model import build_hello

        demo = gui.DemoChannel(2).hello()
        real = build_hello(FakeHost())
        self.assertEqual(set(demo), set(real))
        json.dumps(real)


class GuiLauncherGuardTests(unittest.TestCase):
    def test_refuses_a_non_pi(self):
        import io

        self.assertEqual(run_gui(FakeHost(raspberry_pi=False), stderr=io.StringIO()), 2)

    def test_refuses_without_root(self):
        import io

        self.assertEqual(run_gui(FakeHost(root=False), stderr=io.StringIO()), 1)


if __name__ == "__main__":
    unittest.main()

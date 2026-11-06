import io
import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.cleanup import run_cleanup
from pi_kiosk.cli import main
from pi_kiosk.host import WaylandOutput

AUTOSTART = "/home/pi/.config/labwc/autostart"
RC_XML = "/home/pi/.config/labwc/rc.xml"
CONFIGURED = {
    AUTOSTART: (
        "kanshi &\n"
        "# pi-kiosk-setup:rotation-begin\nwlr-randr --output HDMI-A-1 --transform 270\n# pi-kiosk-setup:rotation-end\n"
        "# pi-kiosk-setup:nosleep-begin\nwlopm --on '*'\n# pi-kiosk-setup:nosleep-end\n"
        "# pi-kiosk-setup:kiosk-begin\nbash /home/pi/.config/pi-kiosk/video-kiosk.sh\n# pi-kiosk-setup:kiosk-end\n"
    ),
    RC_XML: (
        '<?xml version="1.0"?>\n<labwc_config>\n  <keyboard>\n    <default />\n'
        "    <!-- pi-kiosk-setup:cursor-hide-begin -->\n    <keybind key=\"A-W-h\" />\n"
        "    <!-- pi-kiosk-setup:cursor-hide-end -->\n  </keyboard>\n"
        "<!-- pi-kiosk-setup:touch-begin -->\n  <touch mapToOutput=\"HDMI-A-1\" />\n<!-- pi-kiosk-setup:touch-end -->\n"
        "</labwc_config>\n"
    ),
    "/home/pi/.config/pi-kiosk/video-kiosk.sh": "#!/bin/bash\n",
    "/etc/pi-kiosk/kiosk-state.json": "{}",
}


class CleanupTests(unittest.TestCase):
    def test_removes_only_the_blocks_and_files_owned_by_pi_kiosk(self):
        host = FakeHost(files=dict(CONFIGURED))

        run_cleanup(host)

        autostart = host.files[AUTOSTART]
        self.assertEqual(autostart, "kanshi &\n")
        rc_xml = host.files[RC_XML]
        self.assertNotIn("pi-kiosk-setup", rc_xml)
        self.assertIn("<default />", rc_xml)
        self.assertNotIn("/home/pi/.config/pi-kiosk/video-kiosk.sh", host.files)
        self.assertNotIn("/etc/pi-kiosk/kiosk-state.json", host.files)
        for path in (
            "/home/pi/.config/pi-kiosk",
            "/home/pi/.local/share/pi-kiosk",
            "/home/pi/.local/state/pi-kiosk",
            "/etc/pi-kiosk",
            "/usr/local/lib/pi-kiosk",
            "/etc/systemd/system/pi-kiosk-totem-status.service",
            "/etc/systemd/system/pi-kiosk-totem-status.timer",
        ):
            self.assertIn(path, host.removed_paths)

    def test_stops_status_reporting_disables_autologin_and_restores_rotation(self):
        host = FakeHost(
            files=dict(CONFIGURED),
            wayland_outputs=[WaylandOutput("HDMI-A-1"), WaylandOutput("HDMI-A-2")],
        )

        reports = run_cleanup(host)

        self.assertIn(
            ["systemctl", "disable", "--now", "pi-kiosk-totem-status.timer"], host.commands
        )
        self.assertIn(["raspi-config", "nonint", "do_boot_behaviour", "B3"], host.commands)
        self.assertIn(
            [
                "wlr-randr",
                "--output", "HDMI-A-1", "--transform", "normal",
                "--output", "HDMI-A-2", "--transform", "normal",
            ],
            host.desktop_session_commands,
        )
        self.assertTrue(all(report.startswith("Done:") for report in reports))
        self.assertIn("RustDesk", reports[-1])

    def test_is_safe_on_a_pi_that_was_never_configured(self):
        host = FakeHost()

        run_cleanup(host)

        self.assertNotIn(AUTOSTART, host.files)

    def test_cli_cleanup_refuses_a_non_pi(self):
        host = FakeHost(raspberry_pi=False)
        stderr = io.StringIO()

        code = main(argv=["cleanup"], host=host, ui=FakeUI(), stderr=stderr)

        self.assertEqual(code, 2)
        self.assertEqual(host.commands, [])
        self.assertEqual(host.removed_paths, [])

    def test_cli_cleanup_runs_on_a_pi(self):
        host = FakeHost(files=dict(CONFIGURED))
        stdout = io.StringIO()

        code = main(argv=["cleanup"], host=host, ui=FakeUI(), stdout=stdout, stderr=io.StringIO())

        self.assertEqual(code, 0)
        self.assertIn("cleanup completed", stdout.getvalue())



class CleanupLiveSessionTests(unittest.TestCase):
    def test_reloads_labwc_so_the_touch_calibration_is_dropped_now(self):
        host = FakeHost(files=dict(CONFIGURED))

        run_cleanup(host)

        self.assertIn(["labwc", "--reconfigure"], host.desktop_session_commands)

    def test_restores_a_side_by_side_layout_for_landscape_screens(self):
        host = FakeHost(
            wayland_outputs=[
                WaylandOutput("HDMI-A-1", width=1920, height=1080),
                WaylandOutput("HDMI-A-2", width=1920, height=1080),
            ]
        )

        run_cleanup(host)

        self.assertIn(
            [
                "wlr-randr",
                "--output", "HDMI-A-1", "--transform", "normal", "--pos", "0,0",
                "--output", "HDMI-A-2", "--transform", "normal", "--pos", "1920,0",
            ],
            host.desktop_session_commands,
        )


if __name__ == "__main__":
    unittest.main()

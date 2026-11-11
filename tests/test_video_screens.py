"""Each video on its own screen, at every boot.

Tester on a Pi 4 with two screens, five boots: twice the second screen's video
came up wrong (once on the first screen, once shifted over it). VLC chose its
screen itself (--qt-fullscreen-screennumber): an X11 move that labwc applies
late when the window is also changing size, and not at all before the window
is shown. The fullscreen request that follows then lands on the screen under
the pointer. That explains the wrong screen; the shifted video is not
explained. Now labwc moves each VLC to its screen when its window first
appears (a window rule), and VLC sends no position: it only asks for fullscreen.
"""

import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost
from tests.test_video_audio_wait import TV, _LauncherHarness

from pi_kiosk.cleanup import run_cleanup
from pi_kiosk.display import parse_labwc_version
from pi_kiosk.host import VideoSource, WaylandOutput
from pi_kiosk.steps.touch import BEGIN as TOUCH_BEGIN
from pi_kiosk.steps.touch import upsert_touch_block
from pi_kiosk.steps.video_kiosk import (
    SCREENS_RC_BEGIN,
    SCREENS_RC_END,
    VLC_OPTIONS,
    VideoKioskRequest,
    VideoKioskStep,
    VideoScreen,
    launcher_path,
    multi_launcher_script,
    normalize_source,
)
from pi_kiosk.wizard_context import WizardContext

RC_XML = "/home/pi/.config/labwc/rc.xml"
TWO_OUTPUTS = [
    WaylandOutput("HDMI-A-1", "Samsung", 1920, 1080),
    WaylandOutput("HDMI-A-2", "Dell", 1920, 1080),
]
PI_LABWC = (0, 8, 1)

FAKE_VLC = """#!/usr/bin/env bash
echo "0|${PULSE_SINK-unset}|${RESOURCE_NAME-unset}|$*" >>"$FAKE_DIR/vlc.log"
crashes="$FAKE_DIR/crashes"
left="$(cat "$crashes" 2>/dev/null || echo 0)"
if [ "$left" -gt 0 ]; then
  echo $((left - 1)) >"$crashes"
  exit 139
fi
"""


def two_screens() -> VideoKioskRequest:
    first = normalize_source("https://www.dropbox.com/s/one/first.mp4?dl=0")
    second = normalize_source("https://www.dropbox.com/s/two/second.mp4?dl=0")
    return VideoKioskRequest(
        source=first,
        screens=(VideoScreen("HDMI-A-1", first, audio=True), VideoScreen("HDMI-A-2", second)),
    )


def apply(host: FakeHost, request=None) -> str:
    return VideoKioskStep().apply(host, request or two_screens(), WizardContext(host=host, ui=FakeUI()))


class LabwcVersionTests(unittest.TestCase):
    def test_reads_the_version_labwc_prints(self):
        self.assertEqual(parse_labwc_version("labwc 0.8.1 (+xwayland +nls +rsvg +libsfdo)\n"), (0, 8, 1))
        self.assertEqual(parse_labwc_version("labwc 0.9.1-1+rpt2"), (0, 9, 1))

    def test_unknown_output_is_no_version(self):
        self.assertIsNone(parse_labwc_version(""))
        self.assertIsNone(parse_labwc_version("command not found"))


class ScreenRulesTests(unittest.TestCase):
    def test_labwc_moves_each_vlc_to_its_screen(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, labwc_version=PI_LABWC)

        apply(host)

        root = ET.fromstring(host.files[RC_XML])
        rules = {
            rule.get("identifier"): [(action.get("name"), action.get("output")) for action in rule]
            for rule in root.iter("windowRule")
        }
        self.assertEqual(
            rules,
            {
                "pi-kiosk-HDMI-A-1": [("MoveToOutput", "HDMI-A-1")],
                "pi-kiosk-HDMI-A-2": [("MoveToOutput", "HDMI-A-2")],
            },
        )

    def test_vlc_no_longer_moves_itself_where_labwc_does_it(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, labwc_version=PI_LABWC)

        report = apply(host)

        script = host.files[launcher_path(host.home())]
        self.assertNotIn("--qt-fullscreen-screennumber", script)
        self.assertNotIn("xrandr", script)
        self.assertIn('RESOURCE_NAME="pi-kiosk-$output"', script)
        self.assertIn("labwc keeps each video on its screen", report)

    def test_an_older_labwc_keeps_vlcs_own_choice_and_says_so(self):
        # labwc tells XWayland windows apart by their instance name from 0.8.1 on.
        for version, shown in (((0, 8, 0), "labwc 0.8.0"), (None, "this labwc")):
            with self.subTest(version=version):
                host = FakeHost(wayland_outputs=TWO_OUTPUTS, labwc_version=version)

                report = apply(host)

                self.assertIn('--qt-fullscreen-screennumber="$screen"', host.files[launcher_path(host.home())])
                self.assertIn(f"{shown} cannot keep each video on its screen", report)

    def test_the_rules_are_written_once_and_leave_the_rest_of_rc_xml_alone(self):
        existing = upsert_touch_block(
            '<?xml version="1.0"?>\n<openbox_config>\n  <keyboard>\n    <default />\n  </keyboard>\n</openbox_config>\n',
            output="HDMI-A-1",
            matrix=None,
        )
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, labwc_version=PI_LABWC, files={RC_XML: existing})

        apply(host)
        apply(host)

        rc_xml = host.files[RC_XML]
        self.assertEqual(rc_xml.count(SCREENS_RC_BEGIN), 1)
        self.assertEqual(rc_xml.count(SCREENS_RC_END), 1)
        self.assertIn(TOUCH_BEGIN, rc_xml)
        self.assertIn("<default />", rc_xml)
        root = ET.fromstring(rc_xml)
        self.assertEqual(root.tag, "labwc_config")
        self.assertEqual(len(list(root.iter("windowRule"))), 2)

    def test_a_single_screen_setup_drops_the_rules_of_an_earlier_one(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, labwc_version=PI_LABWC)
        apply(host)

        VideoKioskStep().apply(
            host,
            VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            ),
        )

        self.assertNotIn("pi-kiosk-setup:video-screens", host.files[RC_XML])
        self.assertNotIn("windowRule", host.files[RC_XML])

    def test_a_single_screen_setup_does_not_create_rc_xml(self):
        host = FakeHost()

        VideoKioskStep().apply(
            host,
            VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            ),
        )

        self.assertNotIn(RC_XML, host.files)

    def test_cleanup_removes_the_rules(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, labwc_version=PI_LABWC)
        apply(host)

        run_cleanup(host)

        self.assertNotIn("pi-kiosk", host.files[RC_XML])
        ET.fromstring(host.files[RC_XML])

    def test_vlc_does_not_resize_its_window_when_the_video_starts(self):
        # A resize sent right after labwc moved the window carries the old
        # position, and labwc would move the window back.
        self.assertIn("--no-qt-video-autoresize", VLC_OPTIONS)


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "needs bash and python3")
class PinnedLauncherTests(_LauncherHarness):
    def setUp(self):
        super().setUp()
        self.sinks((1, TV))  # sound output present from the start: no audio wait
        (self.dir / "bin" / "vlc").write_text(FAKE_VLC)
        (self.dir / "bin" / "sleep").write_text("#!/usr/bin/env bash\n")
        (self.dir / "bin" / "sleep").chmod(0o755)

    def run_pinned(self) -> dict[str, list[dict]]:
        path = self.config / "video-kiosk.sh"
        path.write_text(
            multi_launcher_script(
                self.vlc,
                [("HDMI-A-1", "/videos/a.mp4", True), ("HDMI-A-2", "/videos/b.mp4", False)],
                labwc_pins=True,
            )
        )
        subprocess.run(["bash", str(path)], env=self.env, check=True, timeout=60)
        starts: dict[str, list[dict]] = {}
        for line in (self.dir / "vlc.log").read_text().splitlines():
            _, sink, name, args = line.split("|", 3)
            starts.setdefault(args.split()[-1], []).append({"sink": sink, "name": name, "args": args})
        return starts

    def test_each_vlc_carries_the_name_labwc_matches(self):
        starts = self.run_pinned()

        self.assertEqual(starts["/videos/a.mp4"][0]["name"], "pi-kiosk-HDMI-A-1")
        self.assertEqual(starts["/videos/b.mp4"][0]["name"], "pi-kiosk-HDMI-A-2")
        for players in starts.values():
            self.assertNotIn("--qt-fullscreen-screennumber", players[0]["args"])
            self.assertIn("--fullscreen", players[0]["args"].split())

    def test_the_sound_still_goes_to_the_chosen_speakers(self):
        starts = self.run_pinned()

        self.assertEqual(starts["/videos/a.mp4"][0]["sink"], TV[1])
        self.assertNotIn("--no-audio", starts["/videos/a.mp4"][0]["args"])
        self.assertEqual(starts["/videos/b.mp4"][0]["sink"], "unset")
        self.assertIn("--no-audio", starts["/videos/b.mp4"][0]["args"])

    def test_a_vlc_started_again_after_a_crash_keeps_its_name(self):
        (self.dir / "crashes").write_text("1")

        starts = self.run_pinned()

        again = next(players for players in starts.values() if len(players) == 2)
        self.assertEqual(again[0]["name"], again[1]["name"])


if __name__ == "__main__":
    unittest.main()

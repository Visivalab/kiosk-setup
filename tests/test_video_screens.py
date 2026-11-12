"""Each video on its own screen, at every boot.

Tester on a Pi 4 with two screens, five boots: twice the second screen's video
came up wrong (once on the first screen, once shifted over it). VLC chooses
its screen itself (--qt-fullscreen-screennumber) and nothing checked the result.

0.3.1 replaced that with a labwc window rule matched by the X11 window name.
On the Pi every video then opened on the first screen: Raspberry Pi's VLC
opens a Wayland window when it can (always on Trixie), which has no X11 name.

Now VLC chooses as before and labwc puts back a video that is on the wrong
screen. Each VLC carries its screen in the window title, which labwc sees for
Wayland and X11 windows alike; the launcher presses a labwc keybind that moves
every such window to its screen, every few seconds.
"""

import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost
from tests.test_video_audio_wait import TV, _LauncherHarness
from tests.test_webapp_kiosk import DEMO_RELEASE_URL

from pi_kiosk.cleanup import run_cleanup
from pi_kiosk.host import VideoSource, WaylandOutput, WebAppSource
from pi_kiosk.steps.kiosk_common import CURSOR_RC_BEGIN
from pi_kiosk.steps.touch import BEGIN as TOUCH_BEGIN
from pi_kiosk.steps.touch import upsert_touch_block
from pi_kiosk.steps.video_kiosk import (
    PIN_KEYBIND,
    PIN_RC_BEGIN,
    PIN_RC_END,
    VLC_OPTIONS,
    VideoKioskRequest,
    VideoKioskStep,
    VideoScreen,
    launcher_path,
    multi_launcher_script,
    normalize_source,
)
from pi_kiosk.steps.webapp_kiosk import WebAppKioskStep
from pi_kiosk.wizard_context import WizardContext

RC_XML = "/home/pi/.config/labwc/rc.xml"
TWO_OUTPUTS = [
    WaylandOutput("HDMI-A-1", "Samsung", 1920, 1080),
    WaylandOutput("HDMI-A-2", "Dell", 1920, 1080),
]
SINGLE = VideoSource(
    shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
    download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
)
# What 0.3.1 wrote, at the end of rc.xml.
OLD_RULES = (
    "<!-- pi-kiosk-setup:video-screens-begin -->\n"
    "  <windowRules>\n"
    '    <windowRule identifier="pi-kiosk-HDMI-A-1">\n'
    '      <action name="MoveToOutput" output="HDMI-A-1" />\n'
    "    </windowRule>\n"
    "  </windowRules>\n"
    "<!-- pi-kiosk-setup:video-screens-end -->\n"
)

FAKE_VLC = """#!/usr/bin/env bash
echo "0|${PULSE_SINK-unset}|${RESOURCE_NAME-unset}|$*" >>"$FAKE_DIR/vlc.log"
REAL_SLEEP 0.5
""".replace("REAL_SLEEP", shutil.which("sleep") or "sleep")

FAKE_WTYPE = """#!/usr/bin/env bash
echo "$*" >>"$FAKE_DIR/wtype.log"
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


def pins(rc_xml: str) -> dict[str, str]:
    """title pattern -> output, from the pin keybind inside <keyboard>."""
    root = ET.fromstring(rc_xml)
    keybinds = [bind for bind in root.findall("keyboard/keybind") if bind.get("key") == PIN_KEYBIND]
    assert len(keybinds) == 1, rc_xml
    found = {}
    for action in keybinds[0].findall("action"):
        assert action.get("name") == "ForEach"
        move = action.find("then/action")
        assert move.get("name") == "MoveToOutput"
        found[action.find("query").get("title")] = move.get("output")
    return found


class PinKeybindTests(unittest.TestCase):
    def test_labwc_can_move_each_video_to_its_screen_by_its_title(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)

        report = apply(host)

        self.assertEqual(
            pins(host.files[RC_XML]),
            {"pi-kiosk-HDMI-A-1 - *": "HDMI-A-1", "pi-kiosk-HDMI-A-2 - *": "HDMI-A-2"},
        )
        self.assertIn("labwc puts back a video that starts on the wrong screen", report)

    def test_the_default_keybinds_stay(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)

        apply(host)

        self.assertIsNotNone(ET.fromstring(host.files[RC_XML]).find("keyboard/default"))

    def test_vlc_still_chooses_its_screen_and_shows_it_in_the_title(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)

        apply(host)

        script = host.files[launcher_path(host.home())]
        self.assertIn('--qt-fullscreen-screennumber="$screen"', script)
        self.assertIn('--input-title-format="pi-kiosk-$output"', script)
        self.assertIn("WTYPE=/usr/bin/wtype", script)
        # 0.3.1, which opened every video on the first screen.
        self.assertNotIn("RESOURCE_NAME", script)
        self.assertNotIn("--no-qt-video-autoresize", VLC_OPTIONS)

    def test_a_second_run_leaves_one_keybind_and_the_rest_of_rc_xml_alone(self):
        existing = upsert_touch_block(
            '<?xml version="1.0"?>\n<openbox_config>\n  <keyboard>\n    <default />\n'
            '    <keybind key="W-e"><action name="Execute" command="pcmanfm" /></keybind>\n'
            "  </keyboard>\n</openbox_config>\n",
            output="HDMI-A-1",
            matrix=None,
        )
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, files={RC_XML: existing})

        apply(host)
        once = host.files[RC_XML]
        apply(host)

        rc_xml = host.files[RC_XML]
        self.assertEqual(rc_xml, once)
        self.assertEqual(rc_xml.count(PIN_RC_BEGIN), 1)
        self.assertIn(TOUCH_BEGIN, rc_xml)
        root = ET.fromstring(rc_xml)
        self.assertEqual(root.tag, "labwc_config")
        self.assertEqual(len(root.findall("keyboard")), 1)
        self.assertEqual({bind.get("key") for bind in root.findall("keyboard/keybind")}, {"W-e", PIN_KEYBIND})
        self.assertEqual(len(pins(rc_xml)), 2)

    def test_it_lives_next_to_the_webapp_cursor_keybind(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)
        WebAppKioskStep().apply(host, WebAppSource(release_url=DEMO_RELEASE_URL))

        apply(host)

        rc_xml = host.files[RC_XML]
        self.assertIn(CURSOR_RC_BEGIN, rc_xml)
        self.assertEqual(len(pins(rc_xml)), 2)

    def test_the_window_rules_of_0_3_1_are_removed(self):
        rc_xml = f'<?xml version="1.0"?>\n<labwc_config>\n{OLD_RULES}</labwc_config>\n'
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, files={RC_XML: rc_xml})

        apply(host)

        self.assertNotIn("windowRule", host.files[RC_XML])
        self.assertNotIn("video-screens", host.files[RC_XML])
        self.assertEqual(len(pins(host.files[RC_XML])), 2)

    def test_a_single_screen_setup_drops_the_keybind_of_an_earlier_one(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)
        apply(host)

        VideoKioskStep().apply(host, SINGLE)

        self.assertNotIn("pi-kiosk-setup:video", host.files[RC_XML])
        self.assertNotIn(PIN_KEYBIND, host.files[RC_XML])
        ET.fromstring(host.files[RC_XML])

    def test_a_single_screen_setup_does_not_create_rc_xml(self):
        host = FakeHost()

        VideoKioskStep().apply(host, SINGLE)

        self.assertNotIn(RC_XML, host.files)

    def test_cleanup_removes_the_keybind_and_the_old_rules(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)
        apply(host)
        host.files[RC_XML] = host.files[RC_XML].replace("</labwc_config>", f"{OLD_RULES}</labwc_config>")

        run_cleanup(host)

        self.assertNotIn("pi-kiosk", host.files[RC_XML])
        self.assertNotIn(PIN_RC_END, host.files[RC_XML])
        ET.fromstring(host.files[RC_XML])

    def test_wtype_is_installed_when_missing(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, wtype=None)

        apply(host)

        self.assertIn(("wtype",), host.installed_packages)
        self.assertIn("WTYPE=/usr/bin/wtype", host.files[launcher_path(host.home())])

    def test_without_wtype_the_videos_still_start_and_the_report_warns(self):
        class NoWtype(FakeHost):
            def ensure_packages_installed(self, packages):
                self.installed_packages.append(packages)

        host = NoWtype(wayland_outputs=TWO_OUTPUTS, wtype=None)

        report = apply(host)

        self.assertIn("WTYPE=''", host.files[launcher_path(host.home())])
        self.assertIn("WARNING - screens", report)


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "needs bash and python3")
class PinnedLauncherTests(_LauncherHarness):
    def setUp(self):
        super().setUp()
        self.sinks((1, TV))  # sound output present from the start: no audio wait
        bin_dir = self.dir / "bin"
        (bin_dir / "vlc").write_text(FAKE_VLC)
        for name, body in (("wtype", FAKE_WTYPE), ("sleep", "#!/usr/bin/env bash\n")):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        self.wtype = str(bin_dir / "wtype")

    def run_two(self, wtype: str) -> dict[str, dict]:
        path = self.config / "video-kiosk.sh"
        path.write_text(
            multi_launcher_script(
                self.vlc,
                [("HDMI-A-1", "/videos/a.mp4", True), ("HDMI-A-2", "/videos/b.mp4", False)],
                wtype=wtype,
            )
        )
        subprocess.run(["bash", str(path)], env=self.env, check=True, timeout=60)
        starts = {}
        for line in (self.dir / "vlc.log").read_text().splitlines():
            _, sink, name, args = line.split("|", 3)
            starts[args.split()[-1]] = {"sink": sink, "name": name, "args": args.split()}
        return starts

    def test_each_vlc_shows_its_screen_in_the_title(self):
        starts = self.run_two(self.wtype)

        self.assertIn("--input-title-format=pi-kiosk-HDMI-A-1", starts["/videos/a.mp4"]["args"])
        self.assertIn("--input-title-format=pi-kiosk-HDMI-A-2", starts["/videos/b.mp4"]["args"])
        self.assertIn("--qt-fullscreen-screennumber=0", starts["/videos/a.mp4"]["args"])
        self.assertIn("--qt-fullscreen-screennumber=1", starts["/videos/b.mp4"]["args"])

    def test_the_keybind_is_pressed_while_the_videos_play(self):
        self.run_two(self.wtype)

        presses = set((self.dir / "wtype.log").read_text().splitlines())
        self.assertEqual(presses, {"-M alt -M logo -P v"})

    def test_the_launcher_still_ends_when_every_vlc_was_closed(self):
        # run_two() returning at all is the check: the pressing loop never ends on its own.
        self.run_two(self.wtype)

        self.assertEqual(list((self.dir / "state" / "pi-kiosk").glob("display-*.pid")), [])

    def test_nothing_is_pressed_without_wtype(self):
        starts = self.run_two("")

        self.assertEqual(len(starts), 2)
        self.assertFalse((self.dir / "wtype.log").exists())

    def test_the_sound_still_goes_to_the_chosen_speakers(self):
        starts = self.run_two(self.wtype)

        self.assertEqual(starts["/videos/a.mp4"]["sink"], TV[1])
        self.assertNotIn("--no-audio", starts["/videos/a.mp4"]["args"])
        self.assertEqual(starts["/videos/b.mp4"]["sink"], "unset")
        self.assertIn("--no-audio", starts["/videos/b.mp4"]["args"])


if __name__ == "__main__":
    unittest.main()

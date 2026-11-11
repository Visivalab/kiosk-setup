"""Runs the rotation block of labwc's autostart with a fake wlr-randr.

Boot as it happens in an installation: the Pi, a TV and a projector share one
power switch, and the projector gives a signal some seconds after the desktop
is up. wlr-randr refuses the whole command when one of its screens is missing,
so without a wait no screen is rotated and both videos open on the same one.

labwc runs autostart with `sh`, top to bottom: the kiosk line below the block
starts only once the block has finished.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.host import WaylandOutput
from pi_kiosk.steps import rotation
from pi_kiosk.steps.kiosk_common import install_kiosk_autostart
from pi_kiosk.steps.rotation import RotationStep
from pi_kiosk.steps.touch import _read_rotation_state
from pi_kiosk.wizard_context import WizardContext

AUTOSTART = "/home/pi/.config/labwc/autostart"
TV = WaylandOutput(name="HDMI-A-1", description="TV", width=1920, height=1080)
PROJECTOR = WaylandOutput(name="HDMI-A-2", description="Projector", width=1920, height=1080)
BOTH = (
    "--output HDMI-A-1 --transform 180 --pos 0,0 "
    "--output HDMI-A-2 --transform normal --pos 1920,0"
)

# Fails like the real one ("unknown output") while a screen has not appeared.
# $FAKE_DIR/outputs holds "<name>:<first call that sees it>" lines.
FAKE_WLR_RANDR = """#!/usr/bin/env bash
count=$(( $(cat "$FAKE_DIR/calls") + 1 ))
echo "$count" >"$FAKE_DIR/calls"
echo "wlr-randr $*" >>"$FAKE_DIR/log"
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then
    after="$(grep "^$2:" "$FAKE_DIR/outputs" | cut -d: -f2)"
    if [ -z "$after" ] || [ "$count" -lt "$after" ]; then
      echo "unknown output $2" >&2
      exit 1
    fi
  fi
  shift
done
"""

FAKE_LOGGER = """#!/usr/bin/env bash
echo "{name} $*" >>"$FAKE_DIR/log"
"""


@unittest.skipUnless(shutil.which("sh") and shutil.which("bash"), "needs sh and bash")
class RotationWaitsForTheScreensTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        scripts = {"wlr-randr": FAKE_WLR_RANDR}
        # No real waiting: sleep and the kiosk launcher only leave a line in the log.
        for name in ("sleep", "bash", "wlopm"):
            scripts[name] = FAKE_LOGGER.format(name=name)
        real_bash = shutil.which("bash")
        for name, body in scripts.items():
            path = bin_dir / name
            path.write_text(body.replace("#!/usr/bin/env bash", f"#!{real_bash}"))
            path.chmod(0o755)
        (self.dir / "calls").write_text("0")
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "FAKE_DIR": str(self.dir),
        }

    def screens(self, **first_seen_at: int) -> None:
        names = {"tv": TV.name, "projector": PROJECTOR.name}
        (self.dir / "outputs").write_text(
            "".join(f"{names[key]}:{call}\n" for key, call in first_seen_at.items())
        )

    def two_screen_autostart(self) -> str:
        host = FakeHost(wayland_outputs=[TV, PROJECTOR])
        RotationStep().apply(
            host,
            {TV.name: "upside-down", PROJECTOR.name: "none"},
            WizardContext(host=host, ui=FakeUI()),
        )
        install_kiosk_autostart(host, "/home/pi/.config/pi-kiosk/video-kiosk.sh")
        return host.files[AUTOSTART]

    def run_autostart(self, content: str) -> list[str]:
        path = self.dir / "autostart"
        path.write_text(content)
        subprocess.run(["sh", str(path)], env=self.env, check=True, timeout=60)
        return (self.dir / "log").read_text().splitlines()

    def test_both_screens_on_applies_the_rotation_at_once(self):
        self.screens(tv=1, projector=1)

        log = self.run_autostart(self.two_screen_autostart())

        self.assertEqual(
            log,
            [f"wlr-randr {BOTH}", "bash /home/pi/.config/pi-kiosk/video-kiosk.sh"],
        )

    def test_waits_for_a_projector_that_turns_on_late_before_starting_the_videos(self):
        self.screens(tv=1, projector=4)

        log = self.run_autostart(self.two_screen_autostart())

        attempts = [line for line in log if line.startswith("wlr-randr")]
        self.assertEqual(attempts, [f"wlr-randr {BOTH}"] * 4)
        self.assertEqual(len([line for line in log if line.startswith("sleep")]), 3)
        # The videos start after the screens are rotated and placed, never before.
        self.assertEqual(log[-2:], [f"wlr-randr {BOTH}", "bash /home/pi/.config/pi-kiosk/video-kiosk.sh"])

    def test_a_screen_that_never_turns_on_does_not_keep_the_other_unrotated(self):
        self.screens(tv=1)

        log = self.run_autostart(self.two_screen_autostart())

        attempts = [line for line in log if line == f"wlr-randr {BOTH}"]
        self.assertEqual(len(attempts), rotation.WAIT_TRIES)
        self.assertEqual(
            log[-3:],
            [
                "wlr-randr --output HDMI-A-1 --transform 180",
                "wlr-randr --output HDMI-A-2 --transform normal",
                "bash /home/pi/.config/pi-kiosk/video-kiosk.sh",
            ],
        )

    def test_one_screen_waits_until_it_is_on(self):
        self.screens(tv=3)
        host = FakeHost()
        RotationStep().apply(host, "upside-down")
        install_kiosk_autostart(host, "/home/pi/.config/pi-kiosk/video-kiosk.sh")

        log = self.run_autostart(host.files[AUTOSTART])

        rotate = "wlr-randr --output HDMI-A-1 --transform 180"
        self.assertEqual([line for line in log if line.startswith("wlr-randr")], [rotate] * 3)
        self.assertEqual(log[-1], "bash /home/pi/.config/pi-kiosk/video-kiosk.sh")

    def test_touch_mapping_still_reads_the_rotation_back_from_the_block(self):
        host = FakeHost(wayland_output="DSI-1")
        RotationStep().apply(host, "clockwise")

        self.assertEqual(_read_rotation_state(host), ("DSI-1", "270"))


if __name__ == "__main__":
    unittest.main()

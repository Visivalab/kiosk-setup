"""Runs the generated launchers with fake pactl/mpv/sleep to check audio start-up.

At boot labwc runs the launcher before PipeWire has published the HDMI outputs.
mpv opens its audio output once, so a player started too early stays silent.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pi_kiosk.steps.video_kiosk import launcher_script, multi_launcher_script

HDMI_0 = "alsa_output.platform-fef00700.hdmi.hdmi-stereo"
HDMI_1 = "alsa_output.platform-fef05700.hdmi.hdmi-stereo"

FAKE_PACTL = """#!/usr/bin/env bash
# Each sink line is "<calls needed>:<name>"; a sink shows up once pactl was asked that often.
count=$(( $(cat "$FAKE_DIR/pactl-calls") + 1 ))
echo "$count" >"$FAKE_DIR/pactl-calls"
while IFS=: read -r after name; do
  [ -n "$name" ] || continue
  if [ "$count" -ge "$after" ]; then printf '57\\t%s\\tPipeWire\\ts32le 2ch 48000Hz\\tSUSPENDED\\n' "$name"; fi
done <"$FAKE_DIR/sinks"
"""

FAKE_MPV = """#!/usr/bin/env bash
echo "$(cat "$FAKE_DIR/pactl-calls") $*" >>"$FAKE_DIR/mpv.log"
"""


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class LauncherWaitsForAudioTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        for name, body in (("pactl", FAKE_PACTL), ("mpv", FAKE_MPV), ("sleep", "#!/bin/sh\nexit 0\n")):
            path = bin_dir / name
            path.write_text(body)
            path.chmod(0o755)
        (self.dir / "pactl-calls").write_text("0\n")
        (self.dir / "sinks").write_text("")
        self.mpv = str(bin_dir / "mpv")
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "FAKE_DIR": str(self.dir),
            "XDG_STATE_HOME": str(self.dir / "state"),
        }

    def sinks(self, *entries: tuple[int, str]) -> None:
        (self.dir / "sinks").write_text("".join(f"{after}:{name}\n" for after, name in entries))

    def run_launcher(self, script: str) -> list[tuple[int, str]]:
        path = self.dir / "video-kiosk.sh"
        path.write_text(script)
        subprocess.run(["bash", str(path)], env=self.env, check=True, timeout=30)
        log = (self.dir / "mpv.log").read_text().splitlines()
        return [(int(line.split(" ", 1)[0]), line.split(" ", 1)[1]) for line in log]

    def test_single_screen_starts_mpv_once_an_audio_output_exists(self):
        self.sinks((3, HDMI_0))

        [(calls, _args)] = self.run_launcher(launcher_script(self.mpv, "/videos/a.mp4", "drm-copy"))

        self.assertEqual(calls, 3)

    def test_single_screen_still_plays_when_no_audio_output_ever_appears(self):
        [(calls, args)] = self.run_launcher(launcher_script(self.mpv, "/videos/a.mp4", "drm-copy"))

        self.assertGreater(calls, 1)
        self.assertIn("/videos/a.mp4", args)

    def test_two_screens_wait_for_the_chosen_output_not_just_any(self):
        self.sinks((1, HDMI_0), (4, HDMI_1))
        script = multi_launcher_script(
            self.mpv,
            [("HDMI-A-1", "/videos/a.mp4", False), ("HDMI-A-2", "/videos/b.mp4", True)],
            audio_device=f"pulse/{HDMI_1}",
        )

        players = self.run_launcher(script)

        self.assertEqual(len(players), 2)
        self.assertTrue(all(calls >= 4 for calls, _ in players))
        with_sound = [args for _, args in players if "--no-audio" not in args]
        self.assertEqual(len(with_sound), 1)
        self.assertIn(f"--audio-device=pulse/{HDMI_1}", with_sound[0])

    def test_two_screens_with_the_default_output_wait_for_any_output(self):
        self.sinks((2, HDMI_0))
        script = multi_launcher_script(
            self.mpv,
            [("HDMI-A-1", "/videos/a.mp4", True), ("HDMI-A-2", "/videos/b.mp4", False)],
        )

        players = self.run_launcher(script)

        self.assertTrue(all(calls == 2 for calls, _ in players))

    def test_muted_screens_do_not_wait_for_audio(self):
        script = multi_launcher_script(
            self.mpv,
            [("HDMI-A-1", "/videos/a.mp4", False), ("HDMI-A-2", "/videos/b.mp4", False)],
        )

        players = self.run_launcher(script)

        self.assertEqual([calls for calls, _ in players], [0, 0])


if __name__ == "__main__":
    unittest.main()

"""Runs the generated launchers and the real audio-route.py with fake PipeWire tools.

Boot as the tester saw it: a TV with speakers and a projector without. The
HDMI outputs appear a few seconds after the desktop, the projector's first.
VLC opens its audio once, so it must start after the TV output exists and be
sent to it, or the sound is lost (silence, or the projector).

The fake vlc logs, per start: pw-dump calls so far|PULSE_SINK|DISPLAY|arguments.
"""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

from pi_kiosk.steps.video_kiosk import AUDIO_ROUTE_SOURCE, launcher_script, multi_launcher_script

TV = ("57", "alsa_output.platform-fef00700.hdmi.hdmi-stereo", "vc4-hdmi-0")
PROJECTOR = ("61", "alsa_output.platform-fef05700.hdmi.hdmi-stereo", "vc4-hdmi-1")

FAKE_PW_DUMP = """#!/usr/bin/env python3
import json, os, pathlib
fake = pathlib.Path(os.environ["FAKE_DIR"])
count = int((fake / "pw-dump-calls").read_text()) + 1
(fake / "pw-dump-calls").write_text(str(count))
nodes = []
for line in (fake / "sinks").read_text().splitlines():
    after, node_id, name, card = line.split(":")
    if count >= int(after):
        nodes.append({"id": int(node_id), "type": "PipeWire:Interface:Node", "info": {"props": {
            "media.class": "Audio/Sink", "node.name": name, "node.description": "HDMI", "alsa.card_name": card}}})
print(json.dumps(nodes))
"""

FAKE_WPCTL = """#!/usr/bin/env bash
echo "$*" >>"$FAKE_DIR/wpctl.log"
"""

FAKE_VLC = """#!/usr/bin/env bash
echo "$(cat "$FAKE_DIR/pw-dump-calls")|${PULSE_SINK-unset}|${DISPLAY-unset}|$*" >>"$FAKE_DIR/vlc.log"
"""

FAKE_XRANDR = """#!/usr/bin/env bash
cat "$FAKE_DIR/xrandr" 2>/dev/null || exit 1
"""


class _LauncherHarness(unittest.TestCase):
    """Runs a generated launcher with fake PipeWire tools, xrandr and vlc on PATH."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        for name, body in (
            ("pw-dump", FAKE_PW_DUMP),
            ("wpctl", FAKE_WPCTL),
            ("vlc", FAKE_VLC),
            ("xrandr", FAKE_XRANDR),
            ("pactl", "#!/usr/bin/env bash\nexit 1\n"),
        ):
            path = bin_dir / name
            path.write_text(body)
            path.chmod(0o755)
        (self.dir / "pw-dump-calls").write_text("0")
        (self.dir / "sinks").write_text("")
        self.config = self.dir / "config"
        self.config.mkdir()
        (self.config / "audio-route.py").write_text(AUDIO_ROUTE_SOURCE)
        self.vlc = str(bin_dir / "vlc")
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "FAKE_DIR": str(self.dir),
            "XDG_STATE_HOME": str(self.dir / "state"),
            "DISPLAY": ":0",
            "PI_KIOSK_X11_DIR": str(self.dir / "no-x11"),
        }
        self.env.pop("PULSE_SINK", None)

    def sinks(self, *entries) -> None:
        (self.dir / "sinks").write_text("".join(f"{after}:{':'.join(sink)}\n" for after, sink in entries))

    def xrandr(self, *lines: str) -> None:
        (self.dir / "xrandr").write_text("".join(f"{line}\n" for line in lines))

    def run_launcher(self, script: str) -> list[dict]:
        path = self.config / "video-kiosk.sh"
        path.write_text(script)
        subprocess.run(["bash", str(path)], env=self.env, check=True, timeout=60)
        players = []
        for line in (self.dir / "vlc.log").read_text().splitlines():
            calls, sink, display, args = line.split("|", 3)
            players.append({"calls": int(calls), "sink": sink, "display": display, "args": args})
        return players

    def two_screens(self, sound_on_first: bool = True, **kwargs) -> str:
        return multi_launcher_script(
            self.vlc,
            [("HDMI-A-1", "/videos/a.mp4", sound_on_first), ("HDMI-A-2", "/videos/b.mp4", False)],
            **kwargs,
        )

    @staticmethod
    def by_video(players: list[dict], video: str) -> dict:
        [player] = [player for player in players if player["args"].endswith(video)]
        return player

    def wpctl(self) -> list[str]:
        path = self.dir / "wpctl.log"
        return path.read_text().splitlines() if path.exists() else []

    def audio_log(self) -> str:
        return (self.dir / "state" / "pi-kiosk" / "audio.log").read_text()


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "needs bash and python3")
class LauncherSendsSoundToTheSpeakersTests(_LauncherHarness):

    def test_two_screens_send_the_sound_to_the_tv_speakers_even_if_the_projector_appears_first(self):
        self.sinks((1, PROJECTOR), (3, TV))
        script = multi_launcher_script(
            self.vlc,
            [("HDMI-A-1", "/videos/tv.mp4", True), ("HDMI-A-2", "/videos/projector.mp4", False)],
        )

        players = self.run_launcher(script)

        self.assertEqual(len(players), 2)
        self.assertTrue(all(player["calls"] >= 3 for player in players))
        tv, projector = self.by_video(players, "/videos/tv.mp4"), self.by_video(players, "/videos/projector.mp4")
        self.assertEqual(tv["sink"], TV[1])
        self.assertNotIn("--no-audio", tv["args"])
        self.assertIn("--no-audio", projector["args"])
        self.assertEqual(projector["sink"], "unset")
        self.assertEqual(self.wpctl(), [f"set-default {TV[0]}"])
        self.assertIn(f"sound goes to: {TV[1]}", self.audio_log())

    def test_an_output_chosen_in_the_wizard_is_used_instead(self):
        self.sinks((1, TV), (1, PROJECTOR))
        players = self.run_launcher(self.two_screens(audio_device=f"pulse/{PROJECTOR[1]}"))

        self.assertEqual(self.by_video(players, "/videos/a.mp4")["sink"], PROJECTOR[1])
        self.assertEqual(self.wpctl(), [f"set-default {PROJECTOR[0]}"])

    def test_muted_screens_do_not_wait_for_audio(self):
        players = self.run_launcher(self.two_screens(sound_on_first=False))

        self.assertEqual([player["calls"] for player in players], [0, 0])

    def test_videos_still_play_if_the_audio_helper_is_missing(self):
        (self.config / "audio-route.py").unlink()
        players = self.run_launcher(self.two_screens())

        self.assertEqual(len(players), 2)
        self.assertEqual([player["sink"] for player in players], ["unset", "unset"])

    def test_single_screen_starts_vlc_once_an_audio_output_exists(self):
        self.sinks((1, ("62", "auto_null", "")), (3, TV))

        [player] = self.run_launcher(launcher_script(self.vlc, "/videos/a.mp4"))

        self.assertEqual(player["calls"], 3)
        self.assertTrue(player["args"].endswith("/videos/a.mp4"))


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "needs bash and python3")
class LauncherPlacesEachVideoTests(_LauncherHarness):
    """VLC picks its fullscreen screen by number, counted as Qt sees XWayland's screens."""

    def setUp(self):
        super().setUp()
        self.sinks((1, TV))  # sound output present from the start: no audio wait

    def screen_of(self, players: list[dict], video: str) -> str:
        args = self.by_video(players, video)["args"]
        return args.split("--qt-fullscreen-screennumber=", 1)[1].split()[0]

    def test_every_launch_overrides_the_users_single_instance_preference(self):
        for script in (launcher_script(self.vlc, "/videos/a.mp4"), self.two_screens()):
            with self.subTest(script=script):
                (self.dir / "vlc.log").unlink(missing_ok=True)

                players = self.run_launcher(script)

                for player in players:
                    self.assertIn("--no-one-instance", player["args"].split())

    def test_screens_are_numbered_in_xwayland_order(self):
        self.xrandr(
            "Screen 0: minimum 16 x 16, current 3840 x 1080, maximum 32767 x 32767",
            "HDMI-A-2 connected 1920x1080+0+0 (normal left inverted right x axis y axis) 0mm x 0mm",
            "   1920x1080     59.96*+",
            "HDMI-A-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 0mm x 0mm",
            "   1920x1080     59.96*+",
        )

        players = self.run_launcher(self.two_screens())

        self.assertEqual(self.screen_of(players, "/videos/a.mp4"), "1")
        self.assertEqual(self.screen_of(players, "/videos/b.mp4"), "0")

    def test_the_primary_screen_counts_first_like_qt(self):
        self.xrandr(
            "HDMI-A-1 connected 1920x1080+0+0 (normal) 0mm x 0mm",
            "HDMI-A-2 connected primary 1920x1080+1920+0 (normal) 0mm x 0mm",
        )

        players = self.run_launcher(self.two_screens())

        self.assertEqual(self.screen_of(players, "/videos/a.mp4"), "1")
        self.assertEqual(self.screen_of(players, "/videos/b.mp4"), "0")

    def test_falls_back_to_the_wizard_order_without_xrandr(self):
        players = self.run_launcher(self.two_screens())

        self.assertEqual(self.screen_of(players, "/videos/a.mp4"), "0")
        self.assertEqual(self.screen_of(players, "/videos/b.mp4"), "1")

    def test_falls_back_when_xwayland_uses_other_output_names(self):
        self.xrandr("XWAYLAND0 connected 1920x1080+0+0", "XWAYLAND1 connected 1920x1080+1920+0")

        players = self.run_launcher(self.two_screens())

        self.assertEqual(self.screen_of(players, "/videos/b.mp4"), "1")

    def test_finds_the_xwayland_display_when_started_without_one(self):
        # "Launch now" from the wizard runs the launcher with WAYLAND_DISPLAY only.
        x11 = self.dir / "x11"
        x11.mkdir()
        server = socket.socket(socket.AF_UNIX)
        self.addCleanup(server.close)
        server.bind(str(x11 / "X1"))
        self.env.pop("DISPLAY")
        self.env["PI_KIOSK_X11_DIR"] = str(x11)

        players = self.run_launcher(self.two_screens())

        self.assertEqual([player["display"] for player in players], [":1", ":1"])

    def test_keeps_the_display_it_was_given(self):
        players = self.run_launcher(launcher_script(self.vlc, "/videos/a.mp4"))

        self.assertEqual(players[0]["display"], ":0")


if __name__ == "__main__":
    unittest.main()

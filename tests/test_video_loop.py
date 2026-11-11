"""A full day of playback, as in a museum.

Nobody restarts a kiosk in an exhibition, so a VLC that crashes must come
back on its own. The fake vlc below "crashes" (exit 139) as many times as its
crash file says, then closes normally (exit 0).
"""

import os
import shutil
import signal
import subprocess
import time
import unittest

from tests.test_video_audio_wait import TV, _LauncherHarness

from pi_kiosk.steps.video_kiosk import VLC_OPTIONS, launcher_script

FAKE_VLC = """#!/usr/bin/env bash
video="${@: -1}"
echo "0|${PULSE_SINK-unset}|${DISPLAY-unset}|$*" >>"$FAKE_DIR/vlc.log"
crashes="$FAKE_DIR/crashes-$(basename "$video")"
left="$(cat "$crashes" 2>/dev/null || echo 0)"
if [ "$left" -gt 0 ]; then
  echo $((left - 1)) >"$crashes"
  exit 139
fi
if [ -e "$FAKE_DIR/keep-playing" ]; then
  echo "$$" >>"$FAKE_DIR/playing"
  exec REAL_SLEEP 600
fi
""".replace("REAL_SLEEP", shutil.which("sleep") or "sleep")

FAKE_SLEEP = """#!/usr/bin/env bash
echo "sleep $*" >>"$FAKE_DIR/sleep.log"
"""


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "needs bash and python3")
class LoopAndRecoveryTests(_LauncherHarness):
    def setUp(self):
        super().setUp()
        self.sinks((1, TV))  # sound output present from the start: no audio wait
        bin_dir = self.dir / "bin"
        (bin_dir / "vlc").write_text(FAKE_VLC)
        (bin_dir / "sleep").write_text(FAKE_SLEEP)
        (bin_dir / "sleep").chmod(0o755)

    def crashes(self, video: str, times: int) -> None:
        (self.dir / f"crashes-{video}").write_text(str(times))

    def launchers(self) -> list[tuple[str, str]]:
        return [
            ("one screen", launcher_script(self.vlc, "/videos/a.mp4")),
            ("two screens", self.two_screens()),
        ]

    def pauses(self) -> list[str]:
        path = self.dir / "sleep.log"
        return path.read_text().splitlines() if path.exists() else []

    def test_the_loop_is_the_one_tried_on_a_real_pi(self):
        # --repeat alone. --input-repeat was considered and dropped: it does not
        # keep two screens in step either, and it was never tried on a Pi.
        self.assertIn("--repeat", VLC_OPTIONS)
        self.assertFalse([option for option in VLC_OPTIONS if option.startswith("--input-repeat")])

    def test_a_single_screen_vlc_that_crashes_is_started_again(self):
        self.crashes("a.mp4", 2)

        players = self.run_launcher(launcher_script(self.vlc, "/videos/a.mp4"))

        self.assertEqual(len(players), 3)
        self.assertEqual(self.pauses(), ["sleep 2", "sleep 2"])

    def test_only_the_screen_that_crashed_is_started_again(self):
        self.crashes("b.mp4", 1)

        players = self.run_launcher(self.two_screens())

        starts = [player["args"].split()[-1] for player in players]
        self.assertEqual(sorted(starts), ["/videos/a.mp4", "/videos/b.mp4", "/videos/b.mp4"])
        self.assertEqual(self.pauses(), ["sleep 2"])
        # It comes back muted on its own screen, like the first time.
        for player in players:
            if player["args"].endswith("/videos/b.mp4"):
                self.assertIn("--no-audio", player["args"])
                self.assertIn("--qt-fullscreen-screennumber=1", player["args"])

    def test_a_vlc_closed_by_a_person_stays_closed(self):
        for name, script in self.launchers():
            with self.subTest(name):
                (self.dir / "vlc.log").unlink(missing_ok=True)

                players = self.run_launcher(script)

                self.assertEqual(len(players), 1 if name == "one screen" else 2)
                self.assertEqual(self.pauses(), [])

    def test_stopping_the_launcher_stops_both_players_for_good(self):
        (self.dir / "keep-playing").write_text("")
        path = self.config / "video-kiosk.sh"
        path.write_text(self.two_screens())
        launcher = subprocess.Popen(["bash", str(path)], env=self.env)
        self.addCleanup(launcher.kill)
        playing = self.dir / "playing"
        state = self.dir / "state" / "pi-kiosk"
        self._wait_until(
            lambda: playing.exists()
            and len(playing.read_text().split()) == 2
            and len([path for path in state.glob("display-*.pid") if path.read_text().strip()]) == 2
        )
        pids = [int(pid) for pid in playing.read_text().split()]
        for pid in pids:
            self.addCleanup(self._kill, pid)
        # The status reporter reads each screen's player from these files.
        self.assertEqual(
            sorted(int((state / f"display-{output}.pid").read_text()) for output in ("HDMI-A-1", "HDMI-A-2")),
            sorted(pids),
        )

        launcher.terminate()
        launcher.wait(timeout=10)

        self._wait_until(lambda: not any(self._alive(pid) for pid in pids))
        self.assertEqual(len(playing.read_text().split()), 2)  # nothing was started again
        self.assertEqual(list(state.glob("display-*.pid")), [])

    def test_a_loop_check_plays_only_the_first_seconds_of_each_video(self):
        self.env["PI_KIOSK_LOOP_SECONDS"] = "15"

        for name, script in self.launchers():
            with self.subTest(name):
                (self.dir / "vlc.log").unlink(missing_ok=True)
                for player in self.run_launcher(script):
                    self.assertIn("--stop-time=15", player["args"].split())

    def test_normal_starts_play_the_whole_video(self):
        for player in self.run_launcher(self.two_screens()):
            self.assertNotIn("--stop-time", player["args"])

    @staticmethod
    def _kill(pid: int) -> None:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            # A killed child of this test stays as a zombie until reaped; it is not playing.
            with open(f"/proc/{pid}/stat") as stat:
                return stat.read().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False

    def _wait_until(self, condition, seconds: float = 10.0) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail("timed out")


if __name__ == "__main__":
    unittest.main()

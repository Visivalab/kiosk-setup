import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from pi_kiosk import audio_route
from pi_kiosk.audio_route import list_sinks, route

TV = {"id": 57, "name": "alsa_output.platform-fef00700.hdmi.hdmi-stereo", "card": "vc4-hdmi-0"}
PROJECTOR = {"id": 61, "name": "alsa_output.platform-fef05700.hdmi.hdmi-stereo", "card": "vc4-hdmi-1"}

PACTL_SINKS = """Sink #57
\tName: alsa_output.platform-fef00700.hdmi.hdmi-stereo
\tDescription: Built-in Audio Digital Stereo (HDMI)
\tProperties:
\t\talsa.card_name = "vc4-hdmi-0"
Sink #61
\tName: alsa_output.platform-fef05700.hdmi.hdmi-stereo
\tDescription: Built-in Audio Digital Stereo (HDMI)
\tProperties:
\t\talsa.card_name = "vc4-hdmi-1"
"""


def pw_dump(*sinks: dict) -> str:
    nodes = [{"id": 30, "type": "PipeWire:Interface:Client", "info": {"props": {}}}]
    for sink in sinks:
        nodes.append(
            {
                "id": sink["id"],
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Audio/Sink",
                        "node.name": sink["name"],
                        "node.description": "Built-in Audio Digital Stereo (HDMI)",
                        "alsa.card_name": sink["card"],
                    }
                },
            }
        )
    nodes.append(
        {"id": 70, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Source", "node.name": "mic"}}}
    )
    return json.dumps(nodes)


class FakeRunner:
    """pw-dump answers come from a list, one per call; other commands succeed."""

    def __init__(self, dumps=None, pactl=None, has_pw_dump=True):
        self.dumps = list(dumps or [])
        self.pactl = pactl
        self.has_pw_dump = has_pw_dump
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv == ["pw-dump"]:
            if not self.has_pw_dump:
                return None
            return self.dumps.pop(0) if len(self.dumps) > 1 else self.dumps[0]
        if argv[:3] == ["pactl", "list", "sinks"]:
            return self.pactl
        return ""

    def defaults(self):
        return [argv for argv in self.calls if "set-default" in argv or "set-default-sink" in argv]


class RouteTests(unittest.TestCase):
    def test_sound_goes_to_the_tv_and_becomes_the_default_not_the_projector(self):
        runner = FakeRunner(dumps=[pw_dump(PROJECTOR, TV)])

        target, _, is_default = route("HDMI-A-1", run=runner, sleep=lambda _: None)

        self.assertEqual(target["name"], TV["name"])
        self.assertTrue(is_default)
        self.assertEqual(runner.defaults(), [["wpctl", "set-default", "57"]])

    def test_second_hdmi_screen_uses_the_second_hdmi_card(self):
        runner = FakeRunner(dumps=[pw_dump(TV, PROJECTOR)])

        target, _, _ = route("HDMI-A-2", run=runner, sleep=lambda _: None)

        self.assertEqual(target["name"], PROJECTOR["name"])

    def test_waits_for_the_speakers_to_appear_at_boot(self):
        sleeps = []
        runner = FakeRunner(dumps=[pw_dump(), pw_dump(PROJECTOR), pw_dump(PROJECTOR, TV)])

        target, _, _ = route("HDMI-A-1", run=runner, sleep=sleeps.append)

        self.assertEqual(target["name"], TV["name"])
        self.assertEqual(len(sleeps), 2)

    def test_gives_up_after_the_wait_and_changes_nothing(self):
        sleeps = []
        runner = FakeRunner(dumps=[pw_dump(PROJECTOR)])

        target, sinks, is_default = route("HDMI-A-1", run=runner, sleep=sleeps.append)

        self.assertIsNone(target)
        self.assertFalse(is_default)
        self.assertEqual([sink["name"] for sink in sinks], [PROJECTOR["name"]])
        self.assertEqual(len(sleeps), audio_route.WAIT_TRIES - 1)
        self.assertEqual(runner.defaults(), [])

    def test_an_output_chosen_in_the_wizard_wins(self):
        runner = FakeRunner(dumps=[pw_dump(TV, PROJECTOR)])

        target, _, _ = route("HDMI-A-1", PROJECTOR["name"], run=runner, sleep=lambda _: None)

        self.assertEqual(target["name"], PROJECTOR["name"])

    def test_works_with_pactl_when_pw_dump_is_missing(self):
        runner = FakeRunner(pactl=PACTL_SINKS, has_pw_dump=False)

        target, _, is_default = route("HDMI-A-1", run=runner, sleep=lambda _: None)

        self.assertEqual(target["name"], TV["name"])
        self.assertTrue(is_default)
        self.assertEqual(runner.defaults(), [["pactl", "set-default-sink", TV["name"]]])

    def test_without_a_screen_it_only_waits_for_any_output(self):
        sleeps = []
        runner = FakeRunner(dumps=[pw_dump(), pw_dump(PROJECTOR)])

        target, _, _ = route(run=runner, sleep=sleeps.append)

        self.assertIsNone(target)
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(runner.defaults(), [])

    def test_no_pipewire_tools_at_all_means_no_outputs(self):
        self.assertEqual(list_sinks(FakeRunner(pactl=None, has_pw_dump=False)), [])


class MainTests(unittest.TestCase):
    def test_prints_the_output_for_mpv_and_writes_a_log(self):
        runner = FakeRunner(dumps=[pw_dump(PROJECTOR, TV)])
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": state}), \
                mock.patch.object(audio_route, "run_command", runner), \
                mock.patch.object(audio_route.time, "sleep", lambda _: None):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(audio_route.main(["HDMI-A-1"]), 0)
            log = (Path(state) / "pi-kiosk" / "audio.log").read_text()

        self.assertEqual(out.getvalue(), f"{TV['name']}\n")
        self.assertIn(f"sound goes to: {TV['name']}", log)
        self.assertIn("made the system default: yes", log)

    def test_log_says_clearly_when_the_speakers_were_not_found(self):
        runner = FakeRunner(dumps=[pw_dump(PROJECTOR)])
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": state}), \
                mock.patch.object(audio_route, "run_command", runner), \
                mock.patch.object(audio_route.time, "sleep", lambda _: None):
            out = io.StringIO()
            with redirect_stdout(out):
                audio_route.main(["HDMI-A-1"])
            log = (Path(state) / "pi-kiosk" / "audio.log").read_text()

        self.assertEqual(out.getvalue(), "")
        self.assertIn("NOT FOUND", log)
        self.assertIn(PROJECTOR["name"], log)


if __name__ == "__main__":
    unittest.main()

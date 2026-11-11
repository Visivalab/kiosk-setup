import io
import json
import unittest
from unittest import mock

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.app import Wizard
from pi_kiosk.cli import main
from pi_kiosk.errors import UserFacingError
from pi_kiosk.host import AudioOutput, WaylandOutput
from pi_kiosk.kiosk_state import KIOSK_STATE_PATH
from pi_kiosk.steps.project_kiosk import AUDIO_DISPLAY_PROMPT, AUDIO_OUTPUT_PROMPT
from pi_kiosk.steps.register_totem import REGISTER_TOTEM_PROMPT
from pi_kiosk.steps.rustdesk import RUSTDESK_INSTALL_PROMPT
from pi_kiosk.steps.touch import TOUCH_DISPLAY_PROMPT
from pi_kiosk.steps.video_kiosk import DROPBOX_PROMPT, VIDEO_NEXT_ACTION_PROMPT
from pi_kiosk.totem_registration import TOTEM_TYPE_PROMPT
from pi_kiosk.totem_status import reporter_config_json
from pi_kiosk.host import TotemStatusReporterConfig

LINK_1 = "https://www.dropbox.com/s/one/first.mp4?dl=0"
TWO_OUTPUTS = [
    WaylandOutput("HDMI-A-1", "Samsung", 1920, 1080),
    WaylandOutput("HDMI-A-2", "Dell", 1920, 1080),
]
SPEAKERS = AudioOutput(id="pulse/hdmi-1", name="HDMI 1")
ANSWERS = {
    "Screen rotation - display 1 (HDMI-A-1 Samsung)": "clockwise",
    "Screen rotation - display 2 (HDMI-A-2 Dell)": "none",
    TOUCH_DISPLAY_PROMPT: "HDMI-A-1",
    RUSTDESK_INSTALL_PROMPT: "no",
    f"{DROPBOX_PROMPT} - display 1 (HDMI-A-1 Samsung)": LINK_1,
    f"{DROPBOX_PROMPT} - display 2 (HDMI-A-2 Dell)": "/media/pi/USB/second.mp4",
    AUDIO_DISPLAY_PROMPT: "HDMI-A-2",
    AUDIO_OUTPUT_PROMPT: SPEAKERS.id,
    REGISTER_TOTEM_PROMPT: "yes",
    "Totem name": "Lobby",
    "Totem description": "",
    "Totem location": "Hall",
    VIDEO_NEXT_ACTION_PROMPT: "close",
}


def two_screen_host(**kwargs) -> FakeHost:
    return FakeHost(
        wayland_outputs=TWO_OUTPUTS,
        audio_outputs=[SPEAKERS],
        touchscreen=True,
        files={"/media/pi/USB/second.mp4": "video"},
        **kwargs,
    )


class TwoScreenWizardTests(unittest.TestCase):
    def test_configures_both_screens_and_saves_the_setup_without_passwords(self):
        host = two_screen_host()
        ui = FakeUI(answers=dict(ANSWERS))

        Wizard(host, ui).run()

        self.assertEqual(host.video_deploy_slots, ["HDMI-A-1", "HDMI-A-2"])
        self.assertEqual(host.video_deploy_requests[1].local_path, "/media/pi/USB/second.mp4")
        self.assertEqual(host.rustdesk_passwords, [])
        state = json.loads(host.files[KIOSK_STATE_PATH])
        self.assertEqual(
            [(item["output"], item["rotation"], item["type"], item["audio"]) for item in state["displays"]],
            [("HDMI-A-1", "clockwise", "video", False), ("HDMI-A-2", "none", "video", True)],
        )
        self.assertEqual(state["audioDevice"], SPEAKERS.id)
        self.assertEqual(state["touchOutput"], "HDMI-A-1")
        self.assertTrue(state["skipRustDesk"])
        self.assertNotIn("password", json.dumps(state).lower().replace("skiprustdesk", ""))

        registration = host.totem_registration_requests[0]
        self.assertEqual([screen["deviceName"] for screen in registration["screens"]], ["HDMI-A-1", "HDMI-A-2"])
        # RustDesk was skipped, so no stale credentials from an earlier install are sent.
        self.assertIsNone(registration["connection"].rustdesk_id)
        self.assertIsNone(registration["connection"].rustdesk_password)
        self.assertEqual(
            [screen["number"] for screen in host.totem_status_reporter_installs[0].screens],
            [1, 2],
        )

    def test_asks_every_question_before_changing_anything(self):
        host = two_screen_host()
        events = []

        class RecordingUI(FakeUI):
            def prompt(self, prompt):
                events.append(("ask", len(host.commands), len(host.files)))
                return super().prompt(prompt)

        Wizard(host, RecordingUI(answers=dict(ANSWERS))).run()

        self.assertTrue(all(commands == 0 and files == 1 for _, commands, files in events))

    def test_still_registers_when_a_video_download_fails(self):
        host = two_screen_host()

        def failing_deploy(*args, **kwargs):
            raise UserFacingError("Could not download the video file: offline.")

        host.deploy_video = failing_deploy
        ui = FakeUI(answers=dict(ANSWERS))

        with self.assertRaises(UserFacingError):
            Wizard(host, ui).run()

        self.assertEqual(len(host.totem_registration_requests), 1)
        self.assertNotIn(KIOSK_STATE_PATH, host.files)
        self.assertTrue(any("register the totem anyway" in message for message in ui.messages))


class RegisterTotemReusesStateTests(unittest.TestCase):
    def test_register_totem_reuses_saved_screens_and_type(self):
        host = two_screen_host()
        Wizard(host, FakeUI(answers=dict(ANSWERS))).run()
        host.totem_registration_requests.clear()
        ui = FakeUI(answers={"Totem name": "Lobby", "Totem description": "", "Totem location": ""})

        with mock.patch.dict("os.environ", {}, clear=False):
            code = main(argv=["register-totem"], host=host, ui=ui, stdout=io.StringIO(), stderr=io.StringIO())

        self.assertEqual(code, 0)
        self.assertNotIn(TOTEM_TYPE_PROMPT, ui.prompts)
        request = host.totem_registration_requests[0]
        self.assertEqual(request["totem_type"], "video")
        self.assertEqual(len(request["screens"]), 2)
        self.assertTrue(any("2 screen(s)" in message for message in ui.messages))


class StatusReporterScreensTests(unittest.TestCase):
    def test_reporter_config_lists_each_screen(self):
        config = json.loads(
            reporter_config_json(
                TotemStatusReporterConfig(
                    endpoint_url="https://example.test/totem-status",
                    token="t",
                    totem_id="pi",
                    totem_type="video",
                    desktop_user="pi",
                    screens=({"number": 1, "deviceName": "HDMI-A-1", "type": "video"},),
                )
            )
        )
        self.assertEqual(config["screens"], [{"number": 1, "output": "HDMI-A-1", "type": "video"}])


class StatusReporterScriptTests(unittest.TestCase):
    def test_each_video_screen_reports_its_own_player(self):
        import os
        import tempfile

        from pi_kiosk.totem_status import reporter_script

        namespace: dict = {"__name__": "reporter"}
        exec(compile(reporter_script(), "totem-status.py", "exec"), namespace)
        with tempfile.TemporaryDirectory() as state_dir:
            Path = namespace["Path"]
            (Path(state_dir) / "display-HDMI-A-1.pid").write_text(str(os.getpid()))
            (Path(state_dir) / "display-HDMI-A-2.pid").write_text("999999999")
            with mock.patch.object(Path, "read_text", autospec=True, side_effect=_comm_as_vlc(Path.read_text)):
                facts = namespace["_screen_facts"](
                    {
                        "stateDir": state_dir,
                        "screens": [
                            {"number": 1, "output": "HDMI-A-1", "type": "video"},
                            {"number": 2, "output": "HDMI-A-2", "type": "video"},
                        ],
                    },
                    True,
                    False,
                )

        self.assertEqual([fact["kiosk_running"] for fact in facts], [True, False])


def _comm_as_vlc(original):
    def read_text(path, *args, **kwargs):
        if str(path).startswith("/proc/") and str(path).endswith("/comm"):
            return "vlc\n"
        return original(path, *args, **kwargs)

    return read_text


if __name__ == "__main__":
    unittest.main()


class StatusReporterMissingPidTests(unittest.TestCase):
    def _facts(self, screens, labwc_running=True):
        import tempfile

        from pi_kiosk.totem_status import reporter_script

        namespace: dict = {"__name__": "reporter"}
        exec(compile(reporter_script(), "totem-status.py", "exec"), namespace)
        with tempfile.TemporaryDirectory() as state_dir:
            return namespace["_screen_facts"]({"stateDir": state_dir, "screens": screens}, labwc_running, False)

    def test_several_screens_without_pid_files_are_stopped(self):
        facts = self._facts(
            [
                {"number": 1, "output": "HDMI-A-1", "type": "video"},
                {"number": 2, "output": "HDMI-A-2", "type": "video"},
            ]
        )
        self.assertEqual([fact["kiosk_running"] for fact in facts], [False, False])

    def test_single_screen_still_follows_the_desktop_session(self):
        facts = self._facts([{"number": 1, "output": "HDMI-A-1", "type": "video"}])
        self.assertEqual([fact["kiosk_running"] for fact in facts], [True])

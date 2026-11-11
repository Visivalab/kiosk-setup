import json
import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.app import Wizard
from pi_kiosk.gui_model import FormError, build_hello, form_to_answers
from pi_kiosk.host import AudioOutput, WaylandOutput, WebAppSource
from pi_kiosk.kiosk_state import KIOSK_STATE_PATH

TWO_OUTPUTS = [
    WaylandOutput("HDMI-A-1", "Samsung", 1920, 1080),
    WaylandOutput("HDMI-A-2", "Dell", 1920, 1080),
]
LINK = "https://www.dropbox.com/s/one/first.mp4?dl=0"


def single_form(**overrides):
    form = {
        "displays": [
            {"output": "HDMI-A-1", "rotation": "clockwise", "type": "webapp", "source": "demo/demo-dist.zip"}
        ],
        "audioDisplay": "",
        "audioDevice": "",
        "touchOutput": "",
        "skipRustDesk": False,
        "rustdeskPassword": "secret",
        "rustdeskPasswordConfirm": "secret",
        "registerTotem": False,
        "totemName": "",
        "totemDescription": "",
        "totemLocation": "",
        "finalAction": "nothing",
    }
    form.update(overrides)
    return form


def two_screen_form(**overrides):
    form = single_form(
        displays=[
            {"output": "HDMI-A-1", "rotation": "none", "type": "video", "source": LINK},
            {"output": "HDMI-A-2", "rotation": "counterclockwise", "type": "video", "source": "/media/pi/USB/b.mp4"},
        ],
        audioDisplay="HDMI-A-2",
        audioDevice="pulse/hdmi-1",
        touchOutput="HDMI-A-2",
    )
    form.update(overrides)
    return form


class HelloTests(unittest.TestCase):
    def test_describes_screens_audio_and_saved_state_for_the_form(self):
        host = FakeHost(
            wayland_outputs=TWO_OUTPUTS,
            audio_outputs=[AudioOutput("pulse/hdmi-1", "HDMI 1")],
            touchscreen=True,
            files={KIOSK_STATE_PATH: json.dumps({"version": 1, "displays": [{"output": "HDMI-A-1"}]})},
        )

        hello = build_hello(host)

        self.assertEqual([item["name"] for item in hello["displays"]], ["HDMI-A-1", "HDMI-A-2"])
        self.assertEqual(hello["displays"][0]["label"], "Display 1 (HDMI-A-1 Samsung) - 1920x1080")
        self.assertEqual(hello["audioOutputs"], [{"id": "pulse/hdmi-1", "name": "HDMI 1"}])
        self.assertTrue(hello["touchscreen"])
        self.assertEqual(hello["state"]["displays"][0]["output"], "HDMI-A-1")
        self.assertEqual([choice["id"] for choice in hello["rotations"]], ["none", "clockwise", "counterclockwise", "upside-down"])


class FormValidationTests(unittest.TestCase):
    def assertRejected(self, host, form, text):
        with self.assertRaises(FormError) as caught:
            form_to_answers(form, host)
        self.assertIn(text, str(caught.exception))

    def test_rejects_mismatched_rustdesk_passwords(self):
        self.assertRejected(FakeHost(), single_form(rustdeskPasswordConfirm="other"), "do not match")

    def test_rejects_missing_rustdesk_password_unless_skipped(self):
        self.assertRejected(FakeHost(), single_form(rustdeskPassword="", rustdeskPasswordConfirm=""), "RustDesk password")
        answers = form_to_answers(single_form(skipRustDesk=True, rustdeskPassword=""), FakeHost())
        self.assertIsNone(answers["rustdesk"])

    def test_rejects_bad_sources_naming_the_display(self):
        self.assertRejected(
            FakeHost(),
            single_form(displays=[{"output": "HDMI-A-1", "rotation": "none", "type": "webapp", "source": "x"}]),
            "Display 1",
        )

    def test_multiple_displays_only_run_videos(self):
        form = two_screen_form()
        form["displays"][0]["type"] = "webapp"
        self.assertRejected(FakeHost(wayland_outputs=TWO_OUTPUTS, files={"/media/pi/USB/b.mp4": "v"}), form, "only run video")

    def test_rejects_missing_local_video(self):
        self.assertRejected(FakeHost(wayland_outputs=TWO_OUTPUTS), two_screen_form(), "not found")

    def test_rejects_a_directory_or_empty_file_before_changing_anything(self):
        for files in ({"/media/pi/USB/b.mp4/inner.mp4": "v"}, {"/media/pi/USB/b.mp4": ""}):
            host = FakeHost(wayland_outputs=TWO_OUTPUTS, files=files)
            self.assertRejected(host, two_screen_form(), "empty or not a file")
            self.assertEqual(host.commands, [])

    def test_rejects_when_the_screens_changed_since_the_window_opened(self):
        self.assertRejected(FakeHost(), two_screen_form(), "displays changed")

    def test_requires_a_totem_name_when_registering(self):
        self.assertRejected(FakeHost(), single_form(registerTotem=True), "totem name")


class FormToAnswersTests(unittest.TestCase):
    def test_single_webapp_form_matches_terminal_answers(self):
        answers = form_to_answers(single_form(finalAction="launch"), FakeHost())

        self.assertEqual(answers["rotation"], "clockwise")
        self.assertEqual(answers["rustdesk"], "secret")
        self.assertEqual(answers["project-kiosk"].project_type, "webapp")
        self.assertEqual(
            answers["project-kiosk"].source,
            WebAppSource("https://visivalab-totems-releases.s3.eu-west-3.amazonaws.com/demo/demo-dist.zip"),
        )
        self.assertIsNone(answers["register-totem"])
        self.assertEqual(answers["next-action"], "simulate")

    def test_two_screen_form_applies_end_to_end(self):
        host = FakeHost(
            wayland_outputs=TWO_OUTPUTS,
            audio_outputs=[AudioOutput("pulse/hdmi-1", "HDMI 1")],
            touchscreen=True,
            files={"/media/pi/USB/b.mp4": "v"},
        )
        form = two_screen_form(registerTotem=True, totemName="Lobby")

        answers = form_to_answers(form, host)
        Wizard(host, FakeUI()).apply_answers(answers)

        self.assertEqual(answers["rotation"], {"HDMI-A-1": "none", "HDMI-A-2": "counterclockwise"})
        self.assertEqual(answers["touch"], "HDMI-A-2")
        self.assertEqual(host.video_deploy_slots, ["HDMI-A-1", "HDMI-A-2"])
        self.assertEqual(len(host.totem_registration_requests[0]["screens"]), 2)
        state = json.loads(host.files[KIOSK_STATE_PATH])
        self.assertEqual(state["audioDisplay"], "HDMI-A-2")
        self.assertIn("--transform 90", host.files["/home/pi/.config/labwc/autostart"])


if __name__ == "__main__":
    unittest.main()

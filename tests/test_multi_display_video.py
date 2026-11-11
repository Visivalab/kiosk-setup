from dataclasses import replace
import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.host import AudioOutput, VideoSource, WaylandOutput
from pi_kiosk.steps.project_kiosk import (
    AUDIO_DISPLAY_PROMPT,
    AUDIO_OUTPUT_PROMPT,
    ProjectKioskStep,
)
from pi_kiosk.steps.video_kiosk import (
    DROPBOX_PROMPT,
    VideoKioskRequest,
    VideoKioskStep,
    VideoScreen,
    launcher_path,
    normalize_source,
)
from pi_kiosk.wizard_context import WizardContext

LINK_1 = "https://www.dropbox.com/s/one/first.mp4?dl=0"
LINK_2 = "https://www.dropbox.com/s/two/second.mp4?dl=0"
TWO_OUTPUTS = [
    WaylandOutput("HDMI-A-1", "Samsung", 1920, 1080),
    WaylandOutput("HDMI-A-2", "Dell", 1920, 1080),
]
SPEAKERS = AudioOutput(id="pulse/alsa_output.hdmi-1", name="HDMI 1")


class LocalVideoSourceTests(unittest.TestCase):
    def test_absolute_paths_are_local_videos(self):
        self.assertEqual(
            normalize_source("/media/pi/USB/videos/../screen1.mp4"),
            VideoSource(
                shared_url="/media/pi/USB/screen1.mp4",
                download_url="",
                local_path="/media/pi/USB/screen1.mp4",
            ),
        )

    def test_ask_rejects_a_local_file_that_does_not_exist(self):
        host = FakeHost(files={"/media/pi/USB/ok.mp4": "data"})
        ui = FakeUI(answers={DROPBOX_PROMPT: ["/media/pi/USB/missing.mp4", "/media/pi/USB/ok.mp4"]})

        request = VideoKioskStep(prompt_for_next_action=False).ask(
            ui, WizardContext(host=host, ui=ui)
        )

        self.assertEqual(request.source.local_path, "/media/pi/USB/ok.mp4")
        self.assertTrue(any("not found" in message for message in ui.messages))


    def test_ask_rejects_a_directory_or_an_empty_file(self):
        host = FakeHost(
            files={"/media/pi/USB/folder/clip.mp4": "data", "/media/pi/USB/empty.mp4": "", "/media/pi/USB/ok.mp4": "v"}
        )
        ui = FakeUI(
            answers={DROPBOX_PROMPT: ["/media/pi/USB/folder", "/media/pi/USB/empty.mp4", "/media/pi/USB/ok.mp4"]}
        )

        request = VideoKioskStep(prompt_for_next_action=False).ask(ui, WizardContext(host=host, ui=ui))

        self.assertEqual(request.source.local_path, "/media/pi/USB/ok.mp4")
        self.assertEqual(sum("empty or not a file" in message for message in ui.messages), 2)


class AskMultiDisplayVideoTests(unittest.TestCase):
    def test_multiple_displays_ask_one_video_each_then_audio(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, audio_outputs=[SPEAKERS])
        ui = FakeUI(
            answers={
                f"{DROPBOX_PROMPT} - display 1 (HDMI-A-1 Samsung)": LINK_1,
                f"{DROPBOX_PROMPT} - display 2 (HDMI-A-2 Dell)": LINK_2,
                AUDIO_DISPLAY_PROMPT: "HDMI-A-2",
                AUDIO_OUTPUT_PROMPT: SPEAKERS.id,
            }
        )

        selection = ProjectKioskStep(prompt_for_next_action=False).ask(
            ui, WizardContext(host=host, ui=ui)
        )

        self.assertEqual(selection.project_type, "video")
        self.assertEqual(
            [(screen.output, screen.source.shared_url, screen.audio) for screen in selection.request.screens],
            [("HDMI-A-1", LINK_1, False), ("HDMI-A-2", LINK_2, True)],
        )
        self.assertEqual(selection.request.audio_device, SPEAKERS.id)
        self.assertEqual(selection.request.audio_device_name, SPEAKERS.name)
        self.assertNotIn("Type of project", ui.prompts)

    def test_skips_output_question_when_no_devices_are_listed(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)
        ui = FakeUI(
            answers={
                f"{DROPBOX_PROMPT} - display 1 (HDMI-A-1 Samsung)": LINK_1,
                f"{DROPBOX_PROMPT} - display 2 (HDMI-A-2 Dell)": LINK_2,
                AUDIO_DISPLAY_PROMPT: "HDMI-A-1",
            }
        )

        selection = ProjectKioskStep(prompt_for_next_action=False).ask(
            ui, WizardContext(host=host, ui=ui)
        )

        self.assertNotIn(AUDIO_OUTPUT_PROMPT, ui.prompts)
        self.assertEqual(selection.request.audio_device, "")


class ApplyMultiDisplayVideoTests(unittest.TestCase):
    def _request(self) -> VideoKioskRequest:
        first = normalize_source(LINK_1)
        return VideoKioskRequest(
            source=first,
            screens=(
                VideoScreen("HDMI-A-1", first, audio=True),
                VideoScreen("HDMI-A-2", normalize_source(LINK_2), audio=False),
            ),
            audio_device=SPEAKERS.id,
            audio_device_name=SPEAKERS.name,
        )

    def test_sound_goes_to_the_speakers_of_the_screen_that_plays_it(self):
        # Tester setup: a TV with speakers and a projector. Left on the default
        # output, PipeWire sent the sound to the projector and nothing was heard.
        tv = AudioOutput("pulse/hdmi0", "HDMI - vc4-hdmi-0", card="vc4-hdmi-0")
        projector = AudioOutput("pulse/hdmi1", "HDMI - vc4-hdmi-1", card="vc4-hdmi-1")
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, audio_outputs=[tv, projector])
        request = replace(self._request(), audio_device="", audio_device_name="")

        VideoKioskStep().apply(host, request, WizardContext(host=host, ui=FakeUI()))

        script = host.files[launcher_path(host.home())]
        self.assertIn("AUDIO_DEVICE=pulse/hdmi0", script)

    def test_a_chosen_output_wins_over_the_screen_speakers(self):
        tv = AudioOutput("pulse/hdmi0", "HDMI - vc4-hdmi-0", card="vc4-hdmi-0")
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, audio_outputs=[tv, SPEAKERS])

        VideoKioskStep().apply(host, self._request(), WizardContext(host=host, ui=FakeUI()))

        script = host.files[launcher_path(host.home())]
        self.assertIn(f"AUDIO_DEVICE={SPEAKERS.id}", script)

    def test_deploys_each_video_into_its_own_display_folder(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)

        report = VideoKioskStep().apply(host, self._request(), WizardContext(host=host, ui=FakeUI()))

        self.assertEqual(host.video_deploy_slots, ["HDMI-A-1", "HDMI-A-2"])
        self.assertIn("2 displays", report)

    def test_launcher_starts_one_player_per_display_with_one_audio_source(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)

        VideoKioskStep().apply(host, self._request(), WizardContext(host=host, ui=FakeUI()))

        script = host.files[launcher_path(host.home())]
        self.assertIn('--fs-screen-name="$output"', script)
        self.assertIn(
            "start_player HDMI-A-1 /home/pi/.local/share/pi-kiosk/video/HDMI-A-1/current/HDMI-A-1.mp4 yes",
            script,
        )
        self.assertIn(
            "start_player HDMI-A-2 /home/pi/.local/share/pi-kiosk/video/HDMI-A-2/current/HDMI-A-2.mp4 no",
            script,
        )
        self.assertIn("AUDIO_DEVICE=pulse/alsa_output.hdmi-1", script)
        self.assertIn("display-$output.pid", script)
        self.assertEqual(script.splitlines()[-1], "wait")

    def test_every_player_uses_the_hardware_decoder_on_a_pi(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)

        VideoKioskStep().apply(host, self._request(), WizardContext(host=host, ui=FakeUI()))

        script = host.files[launcher_path(host.home())]
        self.assertIn("HWDEC=drm-copy", script)
        self.assertIn('--hwdec="$HWDEC"', script)

    def test_autostart_runs_the_shared_launcher_once(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)

        VideoKioskStep().apply(host, self._request(), WizardContext(host=host, ui=FakeUI()))

        autostart = host.files["/home/pi/.config/labwc/autostart"]
        self.assertEqual(autostart.count(f"bash {launcher_path(host.home())}"), 1)


if __name__ == "__main__":
    unittest.main()

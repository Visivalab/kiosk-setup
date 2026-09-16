import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.host import VideoDeployment, VideoSource, WebAppSource
from pi_kiosk.steps.kiosk_common import KIOSK_AUTOSTART_BEGIN
from pi_kiosk.steps.video_kiosk import (
    DROPBOX_PROMPT,
    VIDEO_NEXT_ACTION_PROMPT,
    VideoKioskStep,
    launcher_path,
    normalize_source,
)
from pi_kiosk.wizard_context import WizardContext


class AskVideoKioskStepTests(unittest.TestCase):
    def test_normalizes_dropbox_link_to_direct_download(self):
        ui = FakeUI(answers={DROPBOX_PROMPT: "https://www.dropbox.com/s/example/demo.mp4?dl=0"})

        answer = VideoKioskStep(prompt_for_next_action=False).ask(ui)

        self.assertEqual(
            answer.source,
            VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            ),
        )
        self.assertIsNone(answer.next_action)

    def test_normalize_source_replaces_existing_query_params(self):
        answer = normalize_source(
            "https://www.dropbox.com/scl/fi/example/demo.mp4?rlkey=abc123&dl=0"
        )

        self.assertEqual(
            answer,
            VideoSource(
                shared_url="https://www.dropbox.com/scl/fi/example/demo.mp4?rlkey=abc123&dl=0",
                download_url="https://www.dropbox.com/scl/fi/example/demo.mp4?rlkey=abc123&dl=1",
            ),
        )

    def test_retries_invalid_input_until_valid(self):
        class RetryUI(FakeUI):
            def __init__(self) -> None:
                super().__init__()
                self.values = iter(
                    [
                        "https://example.com/video.mp4",
                        "https://www.dropbox.com/s/example/demo.mp4",
                    ]
                )

            def prompt(self, prompt: str) -> str:
                self.prompts.append(prompt)
                return next(self.values)

        ui = RetryUI()

        answer = VideoKioskStep(prompt_for_next_action=False).ask(ui)

        self.assertEqual(
            answer.source,
            VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            ),
        )
        self.assertTrue(any("dropbox" in message.lower() for message in ui.messages))

    def test_rejects_non_https_links(self):
        with self.assertRaisesRegex(ValueError, "Dropbox"):
            normalize_source("http://www.dropbox.com/s/example/demo.mp4")

    def test_rejects_non_dropbox_hosts(self):
        with self.assertRaisesRegex(ValueError, "Dropbox"):
            normalize_source("https://example.com/s/example/demo.mp4")

    def test_rejects_hosts_that_only_end_with_dropbox_com_text(self):
        with self.assertRaisesRegex(ValueError, "Dropbox"):
            normalize_source("https://evil-dropbox.com/s/example/demo.mp4")

    def test_accepts_dropbox_subdomains(self):
        answer = normalize_source("https://dl.dropbox.com/s/example/demo.mp4")

        self.assertEqual(
            answer,
            VideoSource(
                shared_url="https://dl.dropbox.com/s/example/demo.mp4",
                download_url="https://dl.dropbox.com/s/example/demo.mp4?dl=1",
            ),
        )

    def test_rejects_paths_outside_supported_dropbox_file_routes(self):
        with self.assertRaisesRegex(ValueError, "Dropbox"):
            normalize_source("https://www.dropbox.com/home/demo.mp4")

    def test_accepts_scl_fi_file_links(self):
        answer = normalize_source("https://www.dropbox.com/scl/fi/example/demo.mp4?rlkey=abc123")

        self.assertEqual(
            answer,
            VideoSource(
                shared_url="https://www.dropbox.com/scl/fi/example/demo.mp4?rlkey=abc123",
                download_url="https://www.dropbox.com/scl/fi/example/demo.mp4?rlkey=abc123&dl=1",
            ),
        )


class ApplyVideoKioskStepTests(unittest.TestCase):
    def test_apply_does_not_depend_on_mutable_instance_state_from_ask(self):
        host = FakeHost()
        request = VideoKioskStep().ask(
            FakeUI(
                answers={
                    DROPBOX_PROMPT: "https://www.dropbox.com/s/example/demo.mp4?dl=0",
                    VIDEO_NEXT_ACTION_PROMPT: "simulate",
                }
            )
        )

        report = VideoKioskStep().apply(
            host,
            request,
            WizardContext(
                host=host,
                ui=FakeUI(
                    answers={
                        DROPBOX_PROMPT: "https://www.dropbox.com/s/example/demo.mp4?dl=0",
                        VIDEO_NEXT_ACTION_PROMPT: "simulate",
                    }
                ),
            ),
        )

        self.assertEqual(host.launched_video_paths, [launcher_path(host.home())])
        self.assertIn("launching video now", report.lower())
        self.assertEqual(
            host.video_progress_messages,
            [
                "Preparing Dropbox download",
                "Downloading video file (0%)",
                "Downloading video file (100%)",
                "Deploying video file",
            ],
        )

    def test_simulates_autorun_when_user_chooses_test_option(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                DROPBOX_PROMPT: "https://www.dropbox.com/s/example/demo.mp4?dl=0",
                VIDEO_NEXT_ACTION_PROMPT: "simulate",
            }
        )
        step = VideoKioskStep()
        source = step.ask(ui)

        report = step.apply(host, source, WizardContext(host=host, ui=ui))

        self.assertEqual(host.launched_video_paths, [launcher_path(host.home())])
        self.assertFalse(host.rebooted)
        self.assertIn("launching video now", report.lower())

    def test_reboots_when_user_chooses_production_option(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                DROPBOX_PROMPT: "https://www.dropbox.com/s/example/demo.mp4?dl=0",
                VIDEO_NEXT_ACTION_PROMPT: "reboot",
            }
        )
        step = VideoKioskStep()
        source = step.ask(ui)

        report = step.apply(host, source, WizardContext(host=host, ui=ui))

        self.assertEqual(host.launched_video_paths, [])
        self.assertTrue(host.rebooted)
        self.assertIn("rebooting", report.lower())

    def test_closes_without_launch_when_user_chooses_close_option(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                DROPBOX_PROMPT: "https://www.dropbox.com/s/example/demo.mp4?dl=0",
                VIDEO_NEXT_ACTION_PROMPT: "close",
            }
        )
        step = VideoKioskStep()
        source = step.ask(ui)

        report = step.apply(host, source, WizardContext(host=host, ui=ui))

        self.assertEqual(host.launched_video_paths, [])
        self.assertFalse(host.rebooted)
        self.assertIn("doing nothing now", report.lower())
        self.assertEqual(report.lower().count("next graphical login"), 1)
    def test_deploys_video_and_writes_one_autostart_block(self):
        host = FakeHost(
            deployed_video=VideoDeployment(
                video_path="/home/pi/.local/share/pi-kiosk/video/current/demo.mp4",
                file_name="demo.mp4",
            )
        )
        step = VideoKioskStep()
        ui = FakeUI(
            answers={
                DROPBOX_PROMPT: "https://www.dropbox.com/s/example/demo.mp4?dl=0",
                VIDEO_NEXT_ACTION_PROMPT: "close",
            }
        )
        step.ask(ui)

        report = step.apply(
            host,
            VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            ),
            WizardContext(host=host, ui=ui),
        )

        self.assertEqual(
            host.video_deploy_requests,
            [
                VideoSource(
                    shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                    download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
                )
            ],
        )
        self.assertEqual(host.webapp_deploy_requests, [])
        self.assertEqual(host.installed_packages, [])
        autostart = host.files["/home/pi/.config/labwc/autostart"]
        self.assertIn(KIOSK_AUTOSTART_BEGIN, autostart)
        self.assertIn(f"bash {launcher_path(host.home())}", autostart)
        launcher = host.files[launcher_path(host.home())]
        self.assertIn("mpv", launcher)
        self.assertIn("--loop-file=inf", launcher)
        self.assertIn("--input-touch-emulate-mouse=no", launcher)
        self.assertIn("/home/pi/.local/share/pi-kiosk/video/current/demo.mp4", launcher)
        self.assertIn("demo.mp4", report)
        self.assertEqual(
            host.video_progress_messages,
            [
                "Preparing Dropbox download",
                "Downloading video file (0%)",
                "Downloading video file (100%)",
                "Deploying video file",
            ],
        )

    def test_installs_mpv_when_missing(self):
        host = FakeHost(mpv=None)

        VideoKioskStep().apply(
            host,
            VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            ),
        )

        self.assertEqual(host.installed_packages, [("mpv",)])
        launcher = host.files[launcher_path(host.home())]
        self.assertIn("/usr/bin/mpv", launcher)

    def test_keeps_keyboard_and_mouse_input_available(self):
        launcher = launcher_path("/home/pi")
        host = FakeHost()

        VideoKioskStep().apply(
            host,
            VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            ),
        )

        script = host.files[launcher]
        self.assertIn("--input-touch-emulate-mouse=no", script)
        self.assertNotIn("--input-cursor=no", script)
        self.assertNotIn("--input-vo-keyboard=no", script)

    def test_switching_from_webapp_replaces_the_active_kiosk_launcher(self):
        host = FakeHost()

        from pi_kiosk.steps.webapp_kiosk import WebAppKioskStep, launcher_path as webapp_launcher_path

        WebAppKioskStep().apply(
            host,
            WebAppSource(
                release_url=(
                    "https://visivalab-totems-releases.s3.eu-west-3.amazonaws.com/"
                    "demo-app/demo-app-dist.zip"
                )
            ),
        )
        VideoKioskStep().apply(
            host,
            VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            ),
        )

        autostart = host.files["/home/pi/.config/labwc/autostart"]
        self.assertEqual(autostart.count(KIOSK_AUTOSTART_BEGIN), 1)
        self.assertIn(f"bash {launcher_path(host.home())}", autostart)
        self.assertNotIn(webapp_launcher_path(host.home()), autostart)

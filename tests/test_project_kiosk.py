import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.host import VideoSource, WebAppSource
from pi_kiosk.steps.project_kiosk import NEXT_ACTION_PROMPT, ProjectKioskStep, TYPE_OF_PROJECT_PROMPT
from pi_kiosk.steps.video_kiosk import VIDEO_NEXT_ACTION_PROMPT
from pi_kiosk.wizard_context import WizardContext

DEMO_RELEASE_URL = (
    "https://github.com/Visivalab/demo-app/releases/download/latest/demo-app-dist.zip"
)
RELEASE_URL_PROMPT = "Webapp ZIP URL"


class AskProjectKioskStepTests(unittest.TestCase):
    def test_asks_for_release_zip_url_when_webapp_is_selected(self):
        ui = FakeUI(
            answers={
                TYPE_OF_PROJECT_PROMPT: "webapp",
                RELEASE_URL_PROMPT: DEMO_RELEASE_URL,
            }
        )

        answer = ProjectKioskStep(prompt_for_next_action=False).ask(ui)

        self.assertEqual(answer.project_type, "webapp")
        self.assertEqual(answer.source, WebAppSource(release_url=DEMO_RELEASE_URL))
        self.assertEqual(ui.prompts, [TYPE_OF_PROJECT_PROMPT, RELEASE_URL_PROMPT])

    def test_asks_for_dropbox_link_when_video_is_selected(self):
        ui = FakeUI(
            answers={
                TYPE_OF_PROJECT_PROMPT: "video",
                "Dropbox link": "https://www.dropbox.com/s/example/demo.mp4?dl=0",
            }
        )

        answer = ProjectKioskStep(prompt_for_next_action=False).ask(ui)

        self.assertEqual(answer.project_type, "video")
        self.assertEqual(
            answer.source,
            VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            ),
        )
        self.assertEqual(ui.prompts, [TYPE_OF_PROJECT_PROMPT, "Dropbox link"])


class ApplyProjectKioskStepTests(unittest.TestCase):
    def test_delegates_to_webapp_handler(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                TYPE_OF_PROJECT_PROMPT: "webapp",
                RELEASE_URL_PROMPT: DEMO_RELEASE_URL,
                NEXT_ACTION_PROMPT: "close",
            }
        )
        step = ProjectKioskStep()
        answer = step.ask(ui)

        report = step.apply(host, answer, WizardContext(host=host, ui=ui))

        self.assertEqual(
            host.webapp_deploy_requests,
            [WebAppSource(release_url=DEMO_RELEASE_URL)],
        )
        self.assertEqual(host.video_deploy_requests, [])
        self.assertIn("webapp kiosk", report.lower())

    def test_delegates_to_video_handler(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                TYPE_OF_PROJECT_PROMPT: "video",
                "Dropbox link": "https://www.dropbox.com/s/example/demo.mp4?dl=0",
                VIDEO_NEXT_ACTION_PROMPT: "close",
            }
        )
        step = ProjectKioskStep()
        answer = step.ask(ui)

        report = step.apply(host, answer, WizardContext(host=host, ui=ui))

        self.assertEqual(host.webapp_deploy_requests, [])
        self.assertEqual(
            host.video_deploy_requests,
            [
                VideoSource(
                    shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                    download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
                )
            ],
        )
        self.assertIn("video kiosk", report.lower())

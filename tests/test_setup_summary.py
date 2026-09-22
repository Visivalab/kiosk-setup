import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.display import DISPLAY_CONFIG_KEY, DisplayConfig
from pi_kiosk.host import (
    RustDeskInstall,
    VideoDeployment,
    VideoSource,
    WebAppDeployment,
    WebAppSource,
)
from pi_kiosk.setup_summary import render_setup_summary
from pi_kiosk.steps.autologin import AutologinStep
from pi_kiosk.steps.nosleep import NoSleepStep
from pi_kiosk.steps.project_kiosk import ProjectSelection, ProjectKioskStep
from pi_kiosk.steps.register_totem import RegisterTotemStep
from pi_kiosk.steps.rustdesk import RustDeskStep
from pi_kiosk.steps.setup_summary import SetupSummaryStep
from pi_kiosk.steps.touch import TouchResult, TouchStep
from pi_kiosk.steps.video_kiosk import VideoKioskRequest, VideoKioskStep
from pi_kiosk.steps.webapp_kiosk import WebAppKioskRequest, WebAppKioskStep
from pi_kiosk.totem_registration import (
    TotemRegistrar,
    TotemRegistrationConfig,
    TotemRegistrationRequest,
)
from pi_kiosk.wizard_context import WizardContext


TOTEM_CONFIG = TotemRegistrationConfig(
    endpoint_url="https://dashboard.example.com/register-new-totem",
    token="totem-secret",
)
DEMO_RELEASE_URL = (
    "https://visivalab-totems-releases.s3.eu-west-3.amazonaws.com/"
    "demo-app/demo-app-dist.zip"
)
SCREEN_RELEASE_URL = (
    "https://visivalab-totems-releases.s3.eu-west-3.amazonaws.com/"
    "screen_1_de/screen_1_de-dist.zip"
)


class RenderSetupSummaryTests(unittest.TestCase):
    def test_renders_webapp_summary_with_skipped_registration(self):
        host = FakeHost()
        context = WizardContext(host=host, ui=FakeUI())
        context.record_answer(
            ProjectKioskStep.id,
            ProjectSelection(
                project_type="webapp", request=WebAppKioskRequest(source=WebAppSource(release_url=DEMO_RELEASE_URL))
            ),
        )
        context.record_answer(RegisterTotemStep.id, None)
        context.state[DISPLAY_CONFIG_KEY] = DisplayConfig(
            output="HDMI-A-1",
            transform="270",
            choice_id="clockwise",
            applied_live=True,
        )
        context.state[TouchStep.id] = TouchResult(
            touchscreen_detected=False,
            mapping_updated=False,
        )
        context.state[NoSleepStep.id] = True
        context.state[AutologinStep.id] = "pi"
        context.state[RustDeskStep.id] = RustDeskInstall(
            rustdesk_id="123 456 789",
            asset_name="rustdesk-1.4.3-aarch64.deb",
        )
        context.state[WebAppKioskStep.id] = WebAppDeployment(
            source_url=DEMO_RELEASE_URL,
            app_dir="/home/pi/.local/share/pi-kiosk/webapp/current",
            launcher_path="/home/pi/.config/pi-kiosk/webapp-kiosk.sh",
            server_url="http://127.0.0.1:8080",
            log_tail_command="tail -f /home/pi/.local/state/pi-kiosk/webapp-server.log",
            heartbeat_log_tail_command=(
                "tail -f /home/pi/.local/state/pi-kiosk/webapp-heartbeat.log"
            ),
            autostart_configured=True,
            chromium_kiosk_configured=True,
            cursor_hide_configured=True,
        )

        report = render_setup_summary(context)

        self.assertTrue(report.startswith("Done: setup summary"))
        self.assertIn(
            "- [x] Screen rotation set to clockwise on HDMI-A-1 and applied live; it will persist on future graphical logins",
            report,
        )
        self.assertIn(
            "- [x] RustDesk unattended access was installed and configured with ID 123 456 789",
            report,
        )
        self.assertIn(f"- [x] Downloaded the webapp from {DEMO_RELEASE_URL}", report)
        self.assertIn(
            "- [x] Deployed the webapp to /home/pi/.local/share/pi-kiosk/webapp/current",
            report,
        )
        self.assertIn(
            "- [x] Configured labwc autostart to launch the kiosk on the next graphical login",
            report,
        )
        self.assertIn("- [x] Configured automatic mouse hide after idle", report)
        self.assertIn(
            "- [x] Disabled right-click and text selection in the deployed webapp",
            report,
        )
        self.assertIn("- [x] Totem registration was skipped", report)

    def test_does_not_report_skipped_totem_when_register_step_never_ran(self):
        host = FakeHost()
        context = WizardContext(host=host, ui=FakeUI())

        report = render_setup_summary(context)

        self.assertNotIn("Totem registration was skipped", report)

    def test_webapp_apply_writes_summary_state_from_release_url(self):
        host = FakeHost(
            deployed_webapp=WebAppDeployment(
                source_url=SCREEN_RELEASE_URL,
                app_dir="/home/pi/.local/share/pi-kiosk/webapp/current",
            )
        )
        context = WizardContext(host=host, ui=FakeUI())
        selection = ProjectSelection(
            project_type="webapp",
            request=WebAppKioskRequest(source=WebAppSource(release_url=SCREEN_RELEASE_URL)),
        )
        context.record_answer(ProjectKioskStep.id, selection)
        context.record_answer(RegisterTotemStep.id, None)
        context.state[DISPLAY_CONFIG_KEY] = DisplayConfig(
            output="HDMI-A-1",
            transform="270",
            choice_id="clockwise",
            applied_live=True,
        )
        context.state[TouchStep.id] = TouchResult(
            touchscreen_detected=False,
            mapping_updated=False,
        )
        context.state[NoSleepStep.id] = True
        context.state[AutologinStep.id] = "pi"
        context.state[RustDeskStep.id] = RustDeskInstall(
            rustdesk_id="123 456 789",
            asset_name="rustdesk-1.4.3-aarch64.deb",
        )

        WebAppKioskStep(prompt_for_next_action=False).apply(host, selection.request, context)
        report = SetupSummaryStep().apply(host, context=context)

        self.assertEqual(
            context.state[WebAppKioskStep.id],
            WebAppDeployment(
                source_url=SCREEN_RELEASE_URL,
                app_dir="/home/pi/.local/share/pi-kiosk/webapp/current",
                launcher_path="/home/pi/.config/pi-kiosk/webapp-kiosk.sh",
                server_url="http://127.0.0.1:8080",
                log_tail_command="tail -f /home/pi/.local/state/pi-kiosk/webapp-server.log",
                heartbeat_log_tail_command=(
                    "tail -f /home/pi/.local/state/pi-kiosk/webapp-heartbeat.log"
                ),
                autostart_configured=True,
                chromium_kiosk_configured=True,
                cursor_hide_configured=True,
            ),
        )
        self.assertIn(
            f"- [x] Downloaded the webapp from {SCREEN_RELEASE_URL}",
            report,
        )

    def test_renders_video_summary_with_totem_registration_details(self):
        host = FakeHost(machine_name="pi-kiosk-01")
        context = WizardContext(host=host, ui=FakeUI())
        video_request = VideoKioskRequest(
            source=VideoSource(
                shared_url="https://www.dropbox.com/s/example/demo.mp4?dl=0",
                download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
            )
        )
        context.record_answer(
            ProjectKioskStep.id,
            ProjectSelection(project_type="video", request=video_request),
        )
        registration = TotemRegistrationRequest(
            totem_type="video",
            totem_name="Hall Screen",
            description="",
            location="",
        )
        context.record_answer(RegisterTotemStep.id, registration)
        context.state[DISPLAY_CONFIG_KEY] = DisplayConfig(
            output="HDMI-A-1",
            transform="normal",
            choice_id="none",
            applied_live=False,
        )
        context.state[TouchStep.id] = TouchResult(
            touchscreen_detected=True,
            mapping_updated=False,
        )
        context.state[NoSleepStep.id] = True
        context.state[AutologinStep.id] = "pi"
        context.state[RustDeskStep.id] = RustDeskInstall(
            rustdesk_id="987 654 321",
            asset_name="rustdesk-1.4.3-aarch64.deb",
        )
        VideoKioskStep(prompt_for_next_action=False).apply(host, video_request, context)
        report_message = RegisterTotemStep(
            registrar=TotemRegistrar(config=TOTEM_CONFIG)
        ).apply(host, registration, context)

        self.assertIn("totem registered", report_message.lower())
        self.assertEqual(
            context.state[VideoKioskStep.id],
            VideoDeployment(
                video_path="/home/pi/.local/share/pi-kiosk/video/current/demo.mp4",
                file_name="demo.mp4",
                launcher_path="/home/pi/.config/pi-kiosk/video-kiosk.sh",
                autostart_configured=True,
                fullscreen_loop_configured=True,
            ),
        )
        report = render_setup_summary(context)

        self.assertIn(
            "- [x] Screen rotation set to no rotation on HDMI-A-1; it will apply on the next graphical login",
            report,
        )
        self.assertIn(
            "- [x] Touch screen detected, but no mapping changes were needed because the screen is not rotated",
            report,
        )
        self.assertIn("- [x] Project selected: video", report)
        self.assertIn(
            "- [x] Downloaded the video from https://www.dropbox.com/s/example/demo.mp4?dl=0",
            report,
        )
        self.assertIn(
            "- [x] Deployed the video file to /home/pi/.local/share/pi-kiosk/video/current/demo.mp4",
            report,
        )
        self.assertIn("- [x] Configured mpv for fullscreen looping playback", report)
        self.assertIn(
            '- [x] Registered totem "Hall Screen" for machine pi-kiosk-01. Status reporter installed.',
            report,
        )

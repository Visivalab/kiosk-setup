import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.host import WebAppDeployment, WebAppSource
from pi_kiosk.steps.webapp_kiosk import (
    CURSOR_RC_BEGIN,
    KIOSK_AUTOSTART_BEGIN,
    NEXT_ACTION_CHOICES,
    NEXT_ACTION_PROMPT,
    action_url,
    heartbeat_log_tail_command,
    log_tail_command,
    WebAppKioskStep,
    launcher_path,
    normalize_source,
)
from pi_kiosk.wizard_context import WizardContext

DEMO_RELEASE_URL = (
    "https://github.com/Visivalab/demo-app/releases/download/latest/demo-app-dist.zip"
)
SCREEN_RELEASE_URL = (
    "https://github.com/Visivalab/etruscos_touch/releases/download/"
    "screen-1-de-latest/screen_1_de-dist.zip"
)
SCREEN_S3_URL = (
    "https://visivalab-totems-releases.s3.eu-west-1.amazonaws.com/"
    "webapps/screen_1_de/latest/screen_1_de-dist.zip"
)
RELEASE_URL_PROMPT = "Webapp ZIP URL"


class AskWebAppKioskStepTests(unittest.TestCase):
    def test_close_choice_matches_server_only_behavior(self):
        close_choice = next(choice for choice in NEXT_ACTION_CHOICES if choice.id == "close")

        self.assertIn("app server", close_choice.label.lower())
        self.assertIn("8080", close_choice.label)

    def test_accepts_github_release_zip_url(self):
        ui = FakeUI(answers={RELEASE_URL_PROMPT: DEMO_RELEASE_URL})

        answer = WebAppKioskStep(prompt_for_next_action=False).ask(ui)

        self.assertEqual(answer.source, WebAppSource(release_url=DEMO_RELEASE_URL))
        self.assertIsNone(answer.next_action)

    def test_normalizes_release_url_without_scheme(self):
        source = normalize_source(
            "github.com/Visivalab/demo-app/releases/download/latest/demo-app-dist.zip"
        )

        self.assertEqual(source, WebAppSource(release_url=DEMO_RELEASE_URL))

    def test_normalizes_release_url_and_ignores_query_and_fragment(self):
        source = normalize_source(f"{DEMO_RELEASE_URL}?download=1#asset")

        self.assertEqual(source, WebAppSource(release_url=DEMO_RELEASE_URL))

    def test_normalizes_latest_release_download_url(self):
        source = normalize_source(
            "https://github.com/Visivalab/demo-app/releases/latest/download/demo-app-dist.zip"
        )

        self.assertEqual(
            source,
            WebAppSource(
                release_url=(
                    "https://github.com/Visivalab/demo-app/releases/latest/download/"
                    "demo-app-dist.zip"
                )
            ),
        )

    def test_accepts_release_url_for_nested_project_builds(self):
        source = normalize_source(SCREEN_RELEASE_URL)

        self.assertEqual(source, WebAppSource(release_url=SCREEN_RELEASE_URL))

    def test_accepts_public_s3_zip_url(self):
        source = normalize_source(SCREEN_S3_URL)

        self.assertEqual(source, WebAppSource(release_url=SCREEN_S3_URL))

    def test_preserves_query_parameters_for_non_github_zip_urls(self):
        source = normalize_source(f"{SCREEN_S3_URL}?versionId=example#download")

        self.assertEqual(
            source,
            WebAppSource(release_url=f"{SCREEN_S3_URL}?versionId=example"),
        )

    def test_rejects_insecure_webapp_zip_urls(self):
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            normalize_source(SCREEN_S3_URL.replace("https://", "http://"))

    def test_rejects_https_urls_that_do_not_point_to_a_zip(self):
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            normalize_source("https://example.com/webapps/screen_1_de/latest/")

    def test_retries_invalid_input_until_valid(self):
        class RetryUI(FakeUI):
            def __init__(self) -> None:
                super().__init__()
                self.values = iter(["demo-app", DEMO_RELEASE_URL])

            def prompt(self, prompt: str) -> str:
                self.prompts.append(prompt)
                return next(self.values)

        ui = RetryUI()

        answer = WebAppKioskStep(prompt_for_next_action=False).ask(ui)

        self.assertEqual(answer.source, WebAppSource(release_url=DEMO_RELEASE_URL))
        self.assertTrue(any("public HTTPS webapp ZIP URL" in message for message in ui.messages))
        self.assertTrue(any("example-bucket.s3" in message for message in ui.messages))


class ApplyWebAppKioskStepTests(unittest.TestCase):
    def test_apply_does_not_depend_on_mutable_instance_state_from_ask(self):
        host = FakeHost()
        request = WebAppKioskStep().ask(
            FakeUI(
                answers={
                    RELEASE_URL_PROMPT: DEMO_RELEASE_URL,
                    NEXT_ACTION_PROMPT: "simulate",
                }
            )
        )

        report = WebAppKioskStep().apply(
            host,
            request,
            WizardContext(
                host=host,
                ui=FakeUI(
                    answers={
                        RELEASE_URL_PROMPT: DEMO_RELEASE_URL,
                        NEXT_ACTION_PROMPT: "simulate",
                    }
                ),
            ),
        )

        self.assertEqual(
            host.launched_kiosk_paths,
            [launcher_path(host.home())],
        )
        self.assertIn("simulated autorun", report.lower())
        self.assertEqual(
            host.webapp_progress_messages,
            [
                "Preparing webapp ZIP download",
                "Downloading webapp ZIP",
                "Extracting webapp files",
                "Deploying webapp files",
            ],
        )

    def test_simulates_autorun_when_user_chooses_test_option(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                RELEASE_URL_PROMPT: DEMO_RELEASE_URL,
                NEXT_ACTION_PROMPT: "simulate",
            }
        )
        step = WebAppKioskStep()
        source = step.ask(ui)

        report = step.apply(host, source, WizardContext(host=host, ui=ui))

        self.assertEqual(
            host.launched_kiosk_paths,
            [launcher_path(host.home())],
        )
        self.assertEqual(host.launched_server_paths, [])
        self.assertFalse(host.rebooted)
        self.assertEqual(host.desktop_session_commands, [])
        self.assertIn("simulated autorun", report.lower())
        self.assertIn(log_tail_command(host.home()), report)
        self.assertIn(heartbeat_log_tail_command(host.home()), report)

    def test_reboots_when_user_chooses_production_option(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                RELEASE_URL_PROMPT: DEMO_RELEASE_URL,
                NEXT_ACTION_PROMPT: "reboot",
            }
        )
        step = WebAppKioskStep()
        source = step.ask(ui)

        report = step.apply(host, source, WizardContext(host=host, ui=ui))

        self.assertEqual(host.launched_kiosk_paths, [])
        self.assertEqual(host.launched_server_paths, [])
        self.assertTrue(host.rebooted)
        self.assertIn("rebooting", report.lower())
        self.assertIn(log_tail_command(host.home()), report)
        self.assertIn(heartbeat_log_tail_command(host.home()), report)

    def test_closes_without_launch_when_user_chooses_close_option(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                RELEASE_URL_PROMPT: DEMO_RELEASE_URL,
                NEXT_ACTION_PROMPT: "close",
            }
        )
        step = WebAppKioskStep()
        source = step.ask(ui)

        report = step.apply(host, source, WizardContext(host=host, ui=ui))

        self.assertEqual(host.launched_kiosk_paths, [])
        self.assertEqual(host.launched_server_paths, [launcher_path(host.home())])
        self.assertFalse(host.rebooted)
        self.assertIn(f"is live on {action_url()}", report)
        self.assertIn(log_tail_command(host.home()), report)
        self.assertIn(heartbeat_log_tail_command(host.home()), report)

    def test_deploys_release_zip_and_writes_one_autostart_block(self):
        host = FakeHost(
            deployed_webapp=WebAppDeployment(
                source_url=DEMO_RELEASE_URL,
                app_dir="/home/pi/.local/share/pi-kiosk/webapp/current",
            )
        )
        step = WebAppKioskStep()
        ui = FakeUI(answers={RELEASE_URL_PROMPT: DEMO_RELEASE_URL, NEXT_ACTION_PROMPT: "close"})
        step.ask(ui)

        report = step.apply(
            host,
            WebAppSource(release_url=DEMO_RELEASE_URL),
            WizardContext(host=host, ui=ui),
        )

        self.assertEqual(
            host.webapp_deploy_requests,
            [WebAppSource(release_url=DEMO_RELEASE_URL)],
        )
        self.assertEqual(host.installed_packages, [])
        autostart = host.files["/home/pi/.config/labwc/autostart"]
        self.assertIn(KIOSK_AUTOSTART_BEGIN, autostart)
        self.assertIn(f"bash {launcher_path(host.home())}", autostart)
        rc_xml = host.files["/home/pi/.config/labwc/rc.xml"]
        self.assertIn(CURSOR_RC_BEGIN, rc_xml)
        self.assertIn('<keybind key="A-W-h">', rc_xml)
        self.assertIn('<action name="HideCursor" />', rc_xml)
        launcher = host.files[launcher_path(host.home())]
        self.assertIn('MODE="${1:-kiosk}"', launcher)
        self.assertIn("python3 -m http.server 8080 --bind 127.0.0.1", launcher)
        self.assertIn('HEARTBEAT_LOG_FILE="$LOG_ROOT/webapp-heartbeat.log"', launcher)
        self.assertIn(': >>"$HEARTBEAT_LOG_FILE"', launcher)
        self.assertIn('status_reporter_pid=""', launcher)
        self.assertIn('attempt=0', launcher)
        self.assertIn('while [ "$server_ready" -eq 0 ] && [ "$attempt" -lt 50 ]; do', launcher)
        self.assertIn("sleep 0.2", launcher)
        self.assertIn('attempt=$((attempt + 1))', launcher)
        self.assertIn('if [ "$server_ready" -eq 1 ]; then', launcher)
        self.assertIn("/usr/local/lib/pi-kiosk/totem-status.py /etc/pi-kiosk/totem-status.json", launcher)
        self.assertIn('heartbeat_attempt=1', launcher)
        self.assertIn('while [ "$heartbeat_attempt" -le 12 ]; do', launcher)
        self.assertIn('startup heartbeat attempt %s begin', launcher)
        self.assertIn('startup heartbeat ok on attempt %s', launcher)
        self.assertIn('startup heartbeat attempt %s failed with exit %s', launcher)
        self.assertIn('sleep 5', launcher)
        self.assertIn('startup heartbeat exhausted retries', launcher)
        self.assertIn('startup heartbeat skipped: reporter script or config is missing', launcher)
        self.assertIn('startup heartbeat skipped: local server was not ready after waiting', launcher)
        self.assertIn('if [ "$MODE" = "server-only" ]; then', launcher)
        self.assertIn('  wait "$server_pid"', launcher)
        self.assertIn('idle_pid=""', launcher)
        self.assertIn('  if [ -n "$status_reporter_pid" ]; then', launcher)
        self.assertIn('    wait "$status_reporter_pid" >/dev/null 2>&1 || true', launcher)
        self.assertIn("(sleep 1; /usr/bin/wtype -M alt -M logo -P h >/dev/null 2>&1 || true) &", launcher)
        self.assertIn("if [ -x /usr/bin/wtype ]; then", launcher)
        self.assertIn("if [ -x /usr/bin/wtype ] && [ -x /usr/bin/swayidle ]; then", launcher)
        self.assertIn("swayidle timeout 5 '/usr/bin/wtype -M alt -M logo -P h >/dev/null 2>&1 || true'", launcher)
        self.assertIn('  if [ -n "$idle_pid" ]; then', launcher)
        self.assertIn('    kill "$idle_pid" >/dev/null 2>&1 || true', launcher)
        self.assertIn("chromium-browser", launcher)
        self.assertIn("http://127.0.0.1:8080", launcher)
        self.assertIn("/home/pi/.local/share/pi-kiosk/webapp/current", launcher)
        self.assertIn(DEMO_RELEASE_URL, report)
        self.assertIn("/home/pi/.local/share/pi-kiosk/webapp/current", report)
        self.assertIn(
            "Deployed it to /home/pi/.local/share/pi-kiosk/webapp/current.",
            report,
        )
        self.assertIn(heartbeat_log_tail_command(host.home()), report)
        self.assertEqual(
            host.webapp_progress_messages,
            [
                "Preparing webapp ZIP download",
                "Downloading webapp ZIP",
                "Extracting webapp files",
                "Deploying webapp files",
            ],
        )

    def test_reports_the_release_zip_url_when_host_deploys_it(self):
        host = FakeHost(
            deployed_webapp=WebAppDeployment(
                source_url=DEMO_RELEASE_URL,
                app_dir="/home/pi/.local/share/pi-kiosk/webapp/current",
            )
        )

        step = WebAppKioskStep()
        step.ask(FakeUI(answers={RELEASE_URL_PROMPT: DEMO_RELEASE_URL, NEXT_ACTION_PROMPT: "close"}))
        report = step.apply(host, WebAppSource(release_url=DEMO_RELEASE_URL))

        self.assertIn(DEMO_RELEASE_URL, report)

    def test_replaces_previous_kiosk_block_without_duplication(self):
        path = "/home/pi/.config/labwc/autostart"
        host = FakeHost(
            files={
                path: (
                    "wlopm --on '*' >/dev/null 2>&1 || true\n"
                    "# pi-kiosk-setup:cursor-hide-begin\n"
                    "old cursor command\n"
                    "# pi-kiosk-setup:cursor-hide-end\n"
                    "# pi-kiosk-setup:webapp-kiosk-begin\n"
                    "bash /home/pi/.config/pi-kiosk/old.sh\n"
                    "# pi-kiosk-setup:webapp-kiosk-end\n"
                )
            }
        )

        WebAppKioskStep().apply(host, WebAppSource(release_url=DEMO_RELEASE_URL))

        autostart = host.files[path]
        self.assertEqual(autostart.count(KIOSK_AUTOSTART_BEGIN), 1)
        self.assertNotIn("old.sh", autostart)
        self.assertNotIn("old cursor command", autostart)

    def test_writes_cursor_hide_keybind_into_existing_keyboard_block(self):
        path = "/home/pi/.config/labwc/rc.xml"
        host = FakeHost(
            files={
                path: (
                    '<?xml version="1.0"?>\n'
                    "<labwc_config>\n"
                    "  <keyboard>\n"
                    "    <default />\n"
                    "  </keyboard>\n"
                    "</labwc_config>\n"
                )
            }
        )

        WebAppKioskStep().apply(host, WebAppSource(release_url=DEMO_RELEASE_URL))

        rc_xml = host.files[path]
        self.assertEqual(rc_xml.count(CURSOR_RC_BEGIN), 1)
        self.assertIn("    <default />", rc_xml)
        self.assertIn(
            '      <action name="WarpCursor" x="-1" y="-1" />',
            rc_xml,
        )

    def test_replaces_previous_cursor_hide_keybind_without_duplication(self):
        path = "/home/pi/.config/labwc/rc.xml"
        host = FakeHost(
            files={
                path: (
                    '<?xml version="1.0"?>\n'
                    "<labwc_config>\n"
                    "  <keyboard>\n"
                    "    <default />\n"
                    "    <!-- pi-kiosk-setup:cursor-hide-begin -->\n"
                    '    <keybind key="A-W-h">\n'
                    '      <action name="HideCursor" />\n'
                    "    </keybind>\n"
                    "    <!-- pi-kiosk-setup:cursor-hide-end -->\n"
                    "  </keyboard>\n"
                    "</labwc_config>\n"
                )
            }
        )

        WebAppKioskStep().apply(host, WebAppSource(release_url=DEMO_RELEASE_URL))

        rc_xml = host.files[path]
        self.assertEqual(rc_xml.count(CURSOR_RC_BEGIN), 1)
        self.assertIn(
            '      <action name="WarpCursor" x="-1" y="-1" />',
            rc_xml,
        )

    def test_rejects_missing_chromium(self):
        host = FakeHost(chromium=None)

        with self.assertRaises(RuntimeError):
            WebAppKioskStep().apply(host, WebAppSource(release_url=DEMO_RELEASE_URL))

    def test_rejects_missing_wtype(self):
        host = FakeHost(wtype=None)

        WebAppKioskStep().apply(host, WebAppSource(release_url=DEMO_RELEASE_URL))

        self.assertEqual(host.installed_packages, [("wtype", "swayidle")])
        launcher = host.files[launcher_path(host.home())]
        self.assertIn("/usr/bin/wtype", launcher)

    def test_rejects_missing_swayidle(self):
        host = FakeHost(swayidle=None)

        WebAppKioskStep().apply(host, WebAppSource(release_url=DEMO_RELEASE_URL))

        self.assertEqual(host.installed_packages, [("wtype", "swayidle")])
        launcher = host.files[launcher_path(host.home())]
        self.assertIn("/usr/bin/swayidle", launcher)

    def test_converts_openbox_root_to_labwc_root_before_writing_keybinds(self):
        path = "/home/pi/.config/labwc/rc.xml"
        host = FakeHost(
            files={
                path: (
                    '<?xml version="1.0"?>\n'
                    '<openbox_config xmlns="http://openbox.org/3.4/rc">\n'
                    "  <keyboard>\n"
                    "    <default />\n"
                    "  </keyboard>\n"
                    "</openbox_config>\n"
                )
            }
        )

        WebAppKioskStep().apply(host, WebAppSource(release_url=DEMO_RELEASE_URL))

        rc_xml = host.files[path]
        self.assertIn("<labwc_config", rc_xml)
        self.assertNotIn("<openbox_config", rc_xml)
        self.assertIn('<keybind key="A-W-h">', rc_xml)

    def test_passes_release_url_sources_to_host(self):
        host = FakeHost(
            deployed_webapp=WebAppDeployment(
                source_url=SCREEN_RELEASE_URL,
                app_dir="/home/pi/.local/share/pi-kiosk/webapp/current",
            )
        )
        context = WizardContext(host=host, ui=FakeUI())

        report = WebAppKioskStep().apply(
            host,
            WebAppSource(release_url=SCREEN_RELEASE_URL),
            context,
        )

        self.assertEqual(
            host.webapp_deploy_requests,
            [
                WebAppSource(release_url=SCREEN_RELEASE_URL)
            ],
        )
        self.assertIn(
            f"Done: webapp kiosk deployed from {SCREEN_RELEASE_URL}.",
            report,
        )

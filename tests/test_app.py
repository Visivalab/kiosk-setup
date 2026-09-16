import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.app import NotARaspberryPi, Wizard
from pi_kiosk.host import TotemConnectionDetails, WebAppSource
from pi_kiosk.steps.kiosk_common import NEXT_ACTION_PROMPT
from pi_kiosk.steps.final_action import FinalActionStep
from pi_kiosk.steps.project_kiosk import ProjectKioskStep, TYPE_OF_PROJECT_PROMPT
from pi_kiosk.steps.register_totem import REGISTER_TOTEM_PROMPT, RegisterTotemStep
from pi_kiosk.steps.rotation import RotationStep
from pi_kiosk.steps.rustdesk import RustDeskStep
from pi_kiosk.totem_registration import (
    REGISTER_TOTEM_TOKEN,
    REGISTER_TOTEM_URL,
    RUSTDESK_INSTALL_PROMPT,
    RUSTDESK_SET_PASSWORD_PROMPT,
)
from pi_kiosk.wizard_context import WizardContext

S3_BASE_URL = "https://visivalab-totems-releases.s3.eu-west-3.amazonaws.com/"
DEMO_RELEASE_PATH = "demo-app/demo-app-dist.zip"
DEMO_RELEASE_URL = f"{S3_BASE_URL}{DEMO_RELEASE_PATH}"
RELEASE_URL_PROMPT = "S3 zip - example: screen_1_de/screen_1_de-dist.zip"


class WizardTests(unittest.TestCase):
    def test_asks_rotation_then_reports_each_completed_step(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                "Screen rotation": "clockwise",
                "RustDesk password": "secret-pass",
                TYPE_OF_PROJECT_PROMPT: "webapp",
                RELEASE_URL_PROMPT: DEMO_RELEASE_PATH,
                REGISTER_TOTEM_PROMPT: "no",
                NEXT_ACTION_PROMPT: "simulate",
            }
        )

        reports = Wizard(host, ui).run()

        self.assertEqual(
            ui.prompts,
            [
                "Screen rotation",
                "RustDesk password",
                TYPE_OF_PROJECT_PROMPT,
                RELEASE_URL_PROMPT,
                REGISTER_TOTEM_PROMPT,
                NEXT_ACTION_PROMPT,
            ],
        )
        self.assertEqual(len(reports), 9)
        self.assertTrue(all(item.lower().startswith("done:") for item in reports))
        self.assertEqual(
            [message for message in ui.messages if message.lower().startswith("done:")],
            reports,
        )
        self.assertTrue(any(message.startswith("[....] ") for message in ui.messages))
        self.assertIn("clockwise", reports[0].lower())
        self.assertIn("no touch screen", reports[1].lower())
        self.assertTrue("sleep" in reports[2].lower() or "blank" in reports[2].lower())
        self.assertIn("autologin", reports[3].lower())
        self.assertIn("rustdesk", reports[4].lower())
        self.assertIn("kiosk", reports[5].lower())
        self.assertIn("skipped totem registration", reports[6].lower())
        self.assertIn("setup summary", reports[7].lower())
        self.assertIn("rustdesk unattended access", reports[7].lower())
        self.assertIn("configured automatic mouse hide after idle", reports[7].lower())
        self.assertIn("totem registration was skipped", reports[7].lower())
        self.assertIn("simulated autorun", reports[8].lower())

        autostart = host.files["/home/pi/.config/labwc/autostart"]
        self.assertIn("--transform 270", autostart)
        self.assertIn("wlopm --on", autostart)
        self.assertIn("bash /home/pi/.config/pi-kiosk/webapp-kiosk.sh", autostart)
        self.assertIn(
            ["raspi-config", "nonint", "do_blanking", "1"],
            host.commands,
        )
        self.assertIn(
            ["raspi-config", "nonint", "do_boot_behaviour", "B4"],
            host.commands,
        )
        self.assertEqual(
            host.webapp_deploy_requests,
            [WebAppSource(release_url=DEMO_RELEASE_URL)],
        )
        self.assertEqual(host.rustdesk_passwords, ["secret-pass"])
        self.assertEqual(
            host.launched_kiosk_paths,
            ["/home/pi/.config/pi-kiosk/webapp-kiosk.sh"],
        )

    def test_reports_setup_summary_before_prompting_for_final_action(self):
        class RecordingUI(FakeUI):
            def __init__(self, answers: dict[str, str]) -> None:
                super().__init__(answers=answers)
                self.events: list[tuple[str, str]] = []

            def choose(self, prompt, options):
                self.events.append(("choose", prompt))
                return super().choose(prompt, options)

            def prompt(self, prompt):
                self.events.append(("prompt", prompt))
                return super().prompt(prompt)

            def confirm(self, prompt, default=True):
                self.events.append(("confirm", prompt))
                return super().confirm(prompt, default=default)

            def secret(self, prompt):
                self.events.append(("secret", prompt))
                return super().secret(prompt)

            def info(self, message):
                self.events.append(("info", message))
                super().info(message)

        host = FakeHost()
        ui = RecordingUI(
            answers={
                "Screen rotation": "clockwise",
                "RustDesk password": "secret-pass",
                TYPE_OF_PROJECT_PROMPT: "webapp",
                RELEASE_URL_PROMPT: DEMO_RELEASE_PATH,
                REGISTER_TOTEM_PROMPT: "no",
                NEXT_ACTION_PROMPT: "close",
            }
        )

        Wizard(host, ui).run()

        summary_index = next(
            index
            for index, event in enumerate(ui.events)
            if event[0] == "info" and event[1].startswith("Done: setup summary")
        )
        final_action_prompt_index = next(
            index
            for index, event in enumerate(ui.events)
            if event == ("choose", NEXT_ACTION_PROMPT)
        )

        self.assertLess(summary_index, final_action_prompt_index)

    def test_refuses_to_run_on_a_non_pi(self):
        host = FakeHost(raspberry_pi=False)
        ui = FakeUI(
            answers={
                "Screen rotation": "none",
                "RustDesk password": "secret-pass",
                TYPE_OF_PROJECT_PROMPT: "webapp",
                RELEASE_URL_PROMPT: DEMO_RELEASE_PATH,
                REGISTER_TOTEM_PROMPT: "no",
            }
        )

        with self.assertRaises(NotARaspberryPi):
            Wizard(host, ui).run()

        self.assertEqual(host.commands, [])
        self.assertEqual(host.files, {})

    def test_register_now_reuses_the_password_set_during_rustdesk_install(self):
        host = FakeHost(machine_name="pi-kiosk-01")
        ui = FakeUI(
            answers={
                "Screen rotation": "none",
                "RustDesk password": "secret-pass",
                TYPE_OF_PROJECT_PROMPT: "webapp",
                RELEASE_URL_PROMPT: DEMO_RELEASE_PATH,
                REGISTER_TOTEM_PROMPT: "yes",
                "Totem name": "Hall Screen",
                "Totem description": "",
                "Totem location": "",
                NEXT_ACTION_PROMPT: "close",
            }
        )

        Wizard(host, ui).run()

        request = host.totem_registration_requests[0]
        self.assertEqual(request["endpoint_url"], REGISTER_TOTEM_URL)
        self.assertEqual(request["token"], REGISTER_TOTEM_TOKEN)
        self.assertEqual(
            request["connection"],
            TotemConnectionDetails(
                rustdesk_id="123 456 789",
                rustdesk_password="secret-pass",
            ),
        )
        self.assertNotIn("RustDesk password for backend", ui.prompts)
        self.assertNotIn(RUSTDESK_INSTALL_PROMPT, ui.prompts)
        self.assertNotIn(RUSTDESK_SET_PASSWORD_PROMPT, ui.prompts)

    def test_rotation_step_is_the_only_question(self):
        self.assertEqual(
            Wizard.question_step_ids(),
            [RotationStep.id, RustDeskStep.id, ProjectKioskStep.id, "register-totem", "next-action"],
        )


class RegisterTotemStepTests(unittest.TestCase):
    def test_register_prompt_defaults_to_yes(self):
        class RecordingUI(FakeUI):
            def __init__(self) -> None:
                super().__init__()
                self.confirm_calls: list[tuple[str, bool]] = []

            def confirm(self, prompt: str, default: bool = True) -> bool:
                self.confirm_calls.append((prompt, default))
                return False

        ui = RecordingUI()

        answer = RegisterTotemStep().ask(ui)

        self.assertIsNone(answer)
        self.assertEqual(
            ui.confirm_calls,
            [(REGISTER_TOTEM_PROMPT, True)],
        )

    def test_register_prompt_uses_project_type_from_wizard_context(self):
        host = FakeHost()
        ui = FakeUI(
            answers={
                REGISTER_TOTEM_PROMPT: "yes",
                "Totem name": "Hall Screen",
                "Totem description": "",
                "Totem location": "",
                RUSTDESK_SET_PASSWORD_PROMPT: "yes",
                "RustDesk password": "secret-pass",
            }
        )
        context = WizardContext(host=host, ui=ui)
        context.record_answer(
            ProjectKioskStep.id,
            ProjectKioskStep(prompt_for_next_action=False).ask(
                FakeUI(
                    answers={
                        TYPE_OF_PROJECT_PROMPT: "webapp",
                        RELEASE_URL_PROMPT: DEMO_RELEASE_PATH,
                    }
                )
            ),
        )

        answer = RegisterTotemStep().ask(ui, context)

        self.assertEqual(answer.totem_type, "webapp")


class FinalActionStepTests(unittest.TestCase):
    def test_reads_next_action_from_wizard_context(self):
        host = FakeHost()
        ui = FakeUI(answers={NEXT_ACTION_PROMPT: "simulate"})
        context = WizardContext(host=host, ui=ui)
        context.record_answer(
            ProjectKioskStep.id,
            ProjectKioskStep(prompt_for_next_action=False).ask(
                FakeUI(
                    answers={
                        TYPE_OF_PROJECT_PROMPT: "webapp",
                        RELEASE_URL_PROMPT: DEMO_RELEASE_PATH,
                    }
                )
            ),
        )

        action = FinalActionStep().ask(ui, context)
        report = FinalActionStep().apply(host, action, context)

        self.assertEqual(action, "simulate")
        self.assertIn("simulated autorun", report.lower())

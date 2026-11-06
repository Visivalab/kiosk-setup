import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.host import RustDeskInstall
from pi_kiosk.steps.rustdesk import (
    RUSTDESK_CONFIRM_PROMPT,
    RUSTDESK_INSTALL_PROMPT,
    RustDeskStep,
)
from pi_kiosk.wizard_context import WizardContext


PASSWORD_ANSWERS = {
    "RustDesk password": "secret-pass",
    RUSTDESK_CONFIRM_PROMPT: "secret-pass",
}


class AskRustDeskStepTests(unittest.TestCase):
    def test_password_must_be_typed_twice_and_match(self):
        class MismatchUI(FakeUI):
            def __init__(self) -> None:
                super().__init__()
                self.values = iter(["secret-pass", "typo", "secret-pass", "secret-pass"])

            def secret(self, prompt: str) -> str:
                self.prompts.append(prompt)
                return next(self.values)

        ui = MismatchUI()

        self.assertEqual(RustDeskStep().ask(ui), "secret-pass")
        self.assertTrue(any("do not match" in message for message in ui.messages))

    def test_can_skip_rustdesk(self):
        ui = FakeUI(answers={RUSTDESK_INSTALL_PROMPT: "no"})

        self.assertIsNone(RustDeskStep().ask(ui))
        self.assertNotIn("RustDesk password", ui.prompts)

    def test_skipping_installs_nothing(self):
        host = FakeHost()
        context = WizardContext(host=host, ui=FakeUI())

        report = RustDeskStep().apply(host, None, context)

        self.assertEqual(host.rustdesk_passwords, [])
        self.assertIn("skipped rustdesk", report.lower())
        self.assertTrue(context.state["rustdesk-skipped"])

    def test_asks_for_password(self):
        ui = FakeUI(answers=PASSWORD_ANSWERS)

        answer = RustDeskStep().ask(ui)

        self.assertEqual(answer, "secret-pass")

    def test_retries_empty_password(self):
        class RetryUI(FakeUI):
            def __init__(self) -> None:
                super().__init__()
                self.values = iter(["", "secret-pass", "secret-pass"])

            def secret(self, prompt: str) -> str:
                self.prompts.append(prompt)
                return next(self.values)

        ui = RetryUI()

        answer = RustDeskStep().ask(ui)

        self.assertEqual(answer, "secret-pass")
        self.assertTrue(any("cannot be empty" in message for message in ui.messages))


class ApplyRustDeskStepTests(unittest.TestCase):
    def test_installs_rustdesk_and_reports_id(self):
        host = FakeHost(
            rustdesk_install=RustDeskInstall(
                rustdesk_id="987 654 321",
                asset_name="rustdesk-1.4.3-aarch64.deb",
            )
        )
        step = RustDeskStep()
        ui = FakeUI(answers=PASSWORD_ANSWERS)
        step.ask(ui)

        report = step.apply(host, "secret-pass", WizardContext(host=host, ui=ui))

        self.assertEqual(host.rustdesk_passwords, ["secret-pass"])
        self.assertEqual(
            host.rustdesk_progress_messages,
            [
                "Resolving latest RustDesk release",
                "Downloading RustDesk package",
                "Installing RustDesk package",
                "Configuring RustDesk access",
            ],
        )
        self.assertIn("987 654 321", report)

    def test_apply_does_not_depend_on_mutable_instance_state_from_ask(self):
        host = FakeHost(
            rustdesk_install=RustDeskInstall(
                rustdesk_id="987 654 321",
                asset_name="rustdesk-1.4.3-aarch64.deb",
            )
        )
        ui = FakeUI(answers=PASSWORD_ANSWERS)
        password = RustDeskStep().ask(ui)

        RustDeskStep().apply(host, password, WizardContext(host=host, ui=ui))

        self.assertEqual(
            host.rustdesk_progress_messages,
            [
                "Resolving latest RustDesk release",
                "Downloading RustDesk package",
                "Installing RustDesk package",
                "Configuring RustDesk access",
            ],
        )

import unittest
from uuid import UUID
from unittest import mock

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.errors import UserFacingError
from pi_kiosk.host import TotemConnectionDetails
from pi_kiosk.totem_registration import (
    REGISTER_TOTEM_TOKEN,
    REGISTER_TOTEM_URL,
    RUSTDESK_INSTALL_PROMPT,
    RUSTDESK_PASSWORD_PROMPT,
    RUSTDESK_SET_PASSWORD_PROMPT,
    RUSTDESK_SKIP_WARNING,
    TOTEM_DESCRIPTION_PROMPT,
    TOTEM_LOCATION_PROMPT,
    TOTEM_NAME_PROMPT,
    TOTEM_TYPE_PROMPT,
    default_config,
    TotemRegistrar,
    TotemRegistrationConfig,
)


CONFIG = TotemRegistrationConfig(
    endpoint_url="https://dashboard.example.com/register-new-totem",
    token="totem-secret",
)


def _ui(answers: dict[str, str] | None = None) -> FakeUI:
    values = {
        TOTEM_TYPE_PROMPT: "webapp",
        TOTEM_NAME_PROMPT: "Hall Screen",
        TOTEM_DESCRIPTION_PROMPT: "",
        TOTEM_LOCATION_PROMPT: "",
    }
    values.update(answers or {})
    return FakeUI(answers=values)


class TotemRegistrarIdentityTests(unittest.TestCase):
    def test_same_machine_can_register_separate_totems_and_retry_each(self):
        registrar = TotemRegistrar(config=CONFIG)
        host = FakeHost()
        entrance = registrar.ask(_ui({TOTEM_LOCATION_PROMPT: "Entrance"}))
        exit_totem = registrar.ask(_ui({TOTEM_LOCATION_PROMPT: "Exit"}))

        registrar.register(host, entrance)
        registrar.register(host, exit_totem)
        registrar.register(host, entrance)

        first, second, repeated = [item.totem_id for item in host.totem_status_reporter_installs]
        self.assertEqual(UUID(first).version, 4)
        self.assertEqual(UUID(second).version, 4)
        self.assertNotEqual(first, second)
        self.assertEqual(repeated, first)
        self.assertEqual(
            [item["totem_id"] for item in host.totem_registration_requests],
            [first, second, first],
        )


class TotemRegistrarRustDeskTests(unittest.TestCase):
    def test_default_config_uses_module_constants_when_env_is_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                default_config(),
                TotemRegistrationConfig(
                    endpoint_url=REGISTER_TOTEM_URL,
                    token=REGISTER_TOTEM_TOKEN,
                ),
            )

    def test_default_config_prefers_environment_overrides(self):
        with mock.patch.dict(
            "os.environ",
            {
                "PI_KIOSK_REGISTER_TOTEM_URL": "https://dashboard.example.com/register-new-totem",
                "PI_KIOSK_REGISTER_TOTEM_TOKEN": "totem-secret",
            },
            clear=True,
        ):
            self.assertEqual(default_config(), CONFIG)

    def test_reuses_existing_rustdesk_credentials_without_extra_prompts(self):
        host = FakeHost(saved_rustdesk_password="secret-pass")
        ui = _ui()
        registrar = TotemRegistrar(config=CONFIG)

        request = registrar.ask(ui, host=host)
        report = registrar.register(host, request)

        self.assertNotIn(RUSTDESK_INSTALL_PROMPT, ui.prompts)
        self.assertNotIn(RUSTDESK_SET_PASSWORD_PROMPT, ui.prompts)
        self.assertNotIn(RUSTDESK_PASSWORD_PROMPT, ui.prompts)
        self.assertEqual(host.rustdesk_passwords, [])
        self.assertEqual(host.configured_rustdesk_passwords, [])
        self.assertEqual(
            host.totem_registration_requests[0]["connection"],
            TotemConnectionDetails(
                rustdesk_id="123 456 789",
                rustdesk_password="secret-pass",
            ),
        )
        self.assertIn("registered", report.lower())

    def test_asks_to_install_rustdesk_when_missing(self):
        host = FakeHost(rustdesk_present=False)
        ui = _ui(
            {
                RUSTDESK_INSTALL_PROMPT: "yes",
                RUSTDESK_PASSWORD_PROMPT: "secret-pass",
            }
        )
        registrar = TotemRegistrar(config=CONFIG)

        request = registrar.ask(ui, host=host)

        self.assertIn(RUSTDESK_INSTALL_PROMPT, ui.prompts)
        self.assertNotIn(RUSTDESK_SET_PASSWORD_PROMPT, ui.prompts)
        self.assertTrue(request.install_rustdesk)
        self.assertEqual(request.rustdesk_password, "secret-pass")

    def test_installs_rustdesk_before_posting_when_user_agrees(self):
        host = FakeHost(rustdesk_present=False)
        ui = _ui(
            {
                RUSTDESK_INSTALL_PROMPT: "yes",
                RUSTDESK_PASSWORD_PROMPT: "secret-pass",
            }
        )
        registrar = TotemRegistrar(config=CONFIG)

        request = registrar.ask(ui, host=host)
        registrar.register(host, request, progress=ui.progress)

        self.assertEqual(host.rustdesk_passwords, ["secret-pass"])
        self.assertEqual(host.configured_rustdesk_passwords, [])
        self.assertEqual(
            host.totem_registration_requests[0]["connection"],
            TotemConnectionDetails(
                rustdesk_id="123 456 789",
                rustdesk_password="secret-pass",
            ),
        )
        self.assertEqual(
            host.rustdesk_progress_messages,
            [
                "Resolving latest RustDesk release",
                "Downloading RustDesk package",
                "Installing RustDesk package",
                "Configuring RustDesk access",
            ],
        )

    def test_registers_without_rustdesk_when_user_declines_install(self):
        host = FakeHost(rustdesk_present=False)
        ui = _ui({RUSTDESK_INSTALL_PROMPT: "no"})
        registrar = TotemRegistrar(config=CONFIG)

        request = registrar.ask(ui, host=host)
        registrar.register(host, request)

        self.assertFalse(request.install_rustdesk)
        self.assertIsNone(request.rustdesk_password)
        self.assertNotIn(RUSTDESK_PASSWORD_PROMPT, ui.prompts)
        self.assertIn(f"WARN: {RUSTDESK_SKIP_WARNING}", ui.messages)
        self.assertEqual(host.rustdesk_passwords, [])
        self.assertEqual(
            host.totem_registration_requests[0]["connection"],
            TotemConnectionDetails(rustdesk_id=None, rustdesk_password=None),
        )

    def test_asks_to_set_password_when_rustdesk_is_installed_without_saved_password(self):
        host = FakeHost()
        ui = _ui(
            {
                RUSTDESK_SET_PASSWORD_PROMPT: "yes",
                RUSTDESK_PASSWORD_PROMPT: "secret-pass",
            }
        )
        registrar = TotemRegistrar(config=CONFIG)

        request = registrar.ask(ui, host=host)
        registrar.register(host, request)

        self.assertNotIn(RUSTDESK_INSTALL_PROMPT, ui.prompts)
        self.assertIn(RUSTDESK_SET_PASSWORD_PROMPT, ui.prompts)
        self.assertFalse(request.install_rustdesk)
        self.assertEqual(request.rustdesk_password, "secret-pass")
        self.assertEqual(host.rustdesk_passwords, [])
        self.assertEqual(host.configured_rustdesk_passwords, ["secret-pass"])
        self.assertEqual(
            host.totem_registration_requests[0]["connection"],
            TotemConnectionDetails(
                rustdesk_id="123 456 789",
                rustdesk_password="secret-pass",
            ),
        )

    def test_keeps_existing_rustdesk_when_user_declines_to_set_password(self):
        host = FakeHost()
        ui = _ui({RUSTDESK_SET_PASSWORD_PROMPT: "no"})
        registrar = TotemRegistrar(config=CONFIG)

        request = registrar.ask(ui, host=host)
        registrar.register(host, request)

        self.assertIsNone(request.rustdesk_password)
        self.assertNotIn(RUSTDESK_PASSWORD_PROMPT, ui.prompts)
        self.assertIn(f"WARN: {RUSTDESK_SKIP_WARNING}", ui.messages)
        self.assertEqual(host.configured_rustdesk_passwords, [])
        self.assertEqual(
            host.totem_registration_requests[0]["connection"],
            TotemConnectionDetails(
                rustdesk_id="123 456 789",
                rustdesk_password=None,
            ),
        )

    def test_does_not_post_registration_when_rustdesk_install_fails(self):
        class HostThatFailsInstall(FakeHost):
            def install_rustdesk(self, password, progress=None):
                raise UserFacingError("Could not download the RustDesk package.")

        host = HostThatFailsInstall(rustdesk_present=False)
        ui = _ui(
            {
                RUSTDESK_INSTALL_PROMPT: "yes",
                RUSTDESK_PASSWORD_PROMPT: "secret-pass",
            }
        )
        registrar = TotemRegistrar(config=CONFIG)
        request = registrar.ask(ui, host=host)

        with self.assertRaisesRegex(UserFacingError, "Could not download"):
            registrar.register(host, request)

        self.assertEqual(host.totem_registration_requests, [])

    def test_retries_empty_rustdesk_password(self):
        host = FakeHost(rustdesk_present=False)
        ui = _ui(
            {
                RUSTDESK_INSTALL_PROMPT: "yes",
                RUSTDESK_PASSWORD_PROMPT: ["", "secret-pass"],
            }
        )
        registrar = TotemRegistrar(config=CONFIG)

        request = registrar.ask(ui, host=host)

        self.assertEqual(request.rustdesk_password, "secret-pass")
        self.assertEqual(
            [message for message in ui.messages if message.startswith("WARN: ")],
            ["WARN: RustDesk password cannot be empty."],
        )

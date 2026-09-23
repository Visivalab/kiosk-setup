from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from pi_kiosk.choice import Choice
from pi_kiosk.errors import UserFacingError
from pi_kiosk.host import RustDeskHost, TotemRegistrationHost, TotemStatusReporterConfig
from pi_kiosk.shared_config import config as shared_config
from pi_kiosk.totem_status import derive_status_url
from pi_kiosk.ui import UI

_SHARED_CONFIG = shared_config()
REGISTER_TOTEM_URL = _SHARED_CONFIG["registerTotemUrl"]
REGISTER_TOTEM_TOKEN = _SHARED_CONFIG["registerTotemToken"]

_PROMPTS = _SHARED_CONFIG["prompts"]
TOTEM_TYPE_PROMPT = _PROMPTS["totemType"]
TOTEM_NAME_PROMPT = _PROMPTS["totemName"]
TOTEM_DESCRIPTION_PROMPT = _PROMPTS["totemDescription"]
TOTEM_LOCATION_PROMPT = _PROMPTS["totemLocation"]
RUSTDESK_INSTALL_PROMPT = "RustDesk is not installed. Install it now?"
RUSTDESK_SET_PASSWORD_PROMPT = (
    "RustDesk is installed but no unattended password is saved. "
    "Set one for the backend?"
)
RUSTDESK_SKIP_WARNING = "The dashboard will not have remote access credentials."
RUSTDESK_PASSWORD_PROMPT = _PROMPTS["rustdeskPassword"]
TOTEM_TYPE_CHOICES = [
    Choice(id="webapp", label="Webapp"),
    Choice(id="video", label="Video"),
]


@dataclass(frozen=True)
class TotemRegistrationConfig:
    endpoint_url: str
    token: str


@dataclass(frozen=True)
class TotemRegistrationRequest:
    totem_type: str
    totem_name: str
    description: str
    location: str
    install_rustdesk: bool = False
    rustdesk_password: str | None = None


@dataclass(frozen=True)
class TotemRegistrationResult:
    machine_name: str
    detail: str
    report: str


def default_config() -> TotemRegistrationConfig | None:
    endpoint_url = os.environ.get("PI_KIOSK_REGISTER_TOTEM_URL", REGISTER_TOTEM_URL).strip()
    token = os.environ.get("PI_KIOSK_REGISTER_TOTEM_TOKEN", REGISTER_TOTEM_TOKEN).strip()
    if not endpoint_url or not token:
        return None
    return TotemRegistrationConfig(
        endpoint_url=endpoint_url,
        token=token,
    )


class TotemRegistrar:
    def __init__(self, config: TotemRegistrationConfig | None = None) -> None:
        self._config = config

    def config(self) -> TotemRegistrationConfig | None:
        return self._config if self._config is not None else default_config()

    def ask(
        self,
        ui: UI,
        *,
        totem_type: str | None = None,
        host: RustDeskHost | None = None,
    ) -> TotemRegistrationRequest:
        resolved_totem_type = totem_type or ui.choose(TOTEM_TYPE_PROMPT, list(TOTEM_TYPE_CHOICES))
        resolved_totem_name = _ask_required(ui, TOTEM_NAME_PROMPT)
        resolved_description = _ask_optional(ui, TOTEM_DESCRIPTION_PROMPT)
        resolved_location = _ask_optional(ui, TOTEM_LOCATION_PROMPT)
        install_rustdesk, rustdesk_password = _ask_rustdesk_setup(ui, host)

        return TotemRegistrationRequest(
            totem_type=resolved_totem_type,
            totem_name=resolved_totem_name,
            description=resolved_description,
            location=resolved_location,
            install_rustdesk=install_rustdesk,
            rustdesk_password=rustdesk_password,
        )

    def register(
        self,
        host: TotemRegistrationHost,
        registration: TotemRegistrationRequest,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> str:
        return self.register_result(host, registration, progress=progress).report

    def register_result(
        self,
        host: TotemRegistrationHost,
        registration: TotemRegistrationRequest,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> TotemRegistrationResult:
        config = self.config()
        if config is None:
            raise UserFacingError("Totem registration is not configured.")

        machine_name = host.machine_name().strip()
        if not machine_name:
            raise UserFacingError("Could not determine the machine name for this device.")

        if registration.install_rustdesk:
            password = registration.rustdesk_password
            if not password:
                raise UserFacingError("RustDesk password cannot be empty.")
            host.install_rustdesk(password, progress=progress)
        elif registration.rustdesk_password:
            host.configure_rustdesk_password(registration.rustdesk_password)

        connection = host.connection_details()
        host.register_totem(
            config.endpoint_url,
            config.token,
            machine_name,
            registration.totem_type,
            registration.totem_name,
            registration.description,
            registration.location,
            connection,
        )
        status_endpoint_url = derive_status_url(config.endpoint_url)
        if status_endpoint_url:
            warning = host.install_totem_status_reporter(
                TotemStatusReporterConfig(
                    endpoint_url=status_endpoint_url,
                    token=config.token,
                    totem_id=machine_name,
                    totem_type=registration.totem_type,
                    desktop_user=host.user(),
                )
            )
            if warning:
                return TotemRegistrationResult(
                    machine_name=machine_name,
                    detail=warning,
                    report=(
                        f"Done: totem registered for machine {machine_name}. "
                        f"{warning}"
                    ),
                )
            return TotemRegistrationResult(
                machine_name=machine_name,
                detail="Status reporter installed.",
                report=(
                    f"Done: totem registered for machine {machine_name}. "
                    "Status reporter installed."
                ),
            )
        detail = (
            "Status reporter was not installed because no status endpoint is configured."
        )
        return TotemRegistrationResult(
            machine_name=machine_name,
            detail=detail,
            report=(
                f"Done: totem registered for machine {machine_name}. "
                f"{detail}"
            ),
        )


def _ask_rustdesk_setup(ui: UI, host: RustDeskHost | None) -> tuple[bool, str | None]:
    if host is None:
        return False, None
    if host.rustdesk_installed():
        if host.connection_details().rustdesk_password:
            return False, None
        if ui.confirm(RUSTDESK_SET_PASSWORD_PROMPT, default=True):
            return False, _ask_required_secret(ui, RUSTDESK_PASSWORD_PROMPT)
        ui.warn(RUSTDESK_SKIP_WARNING)
        return False, None
    if ui.confirm(RUSTDESK_INSTALL_PROMPT, default=True):
        return True, _ask_required_secret(ui, RUSTDESK_PASSWORD_PROMPT)
    ui.warn(RUSTDESK_SKIP_WARNING)
    return False, None


def _ask_required(ui: UI, prompt: str) -> str:
    while True:
        value = ui.prompt(prompt).strip()
        if value:
            return value
        ui.warn(f"{prompt} cannot be empty.")


def _ask_required_secret(ui: UI, prompt: str) -> str:
    while True:
        value = ui.secret(prompt).strip()
        if value:
            return value
        ui.warn(f"{prompt} cannot be empty.")


def _ask_optional(ui: UI, prompt: str) -> str:
    return ui.prompt(prompt).strip()

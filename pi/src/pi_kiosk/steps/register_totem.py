from __future__ import annotations

from typing import TYPE_CHECKING

from dataclasses import replace

from pi_kiosk.host import TotemRegistrationHost
from pi_kiosk.kiosk_state import build_state, screens_report
from pi_kiosk.shared_config import config as shared_config
from pi_kiosk.steps.project_kiosk import ProjectKioskStep
from pi_kiosk.steps.rustdesk import RustDeskStep
from pi_kiosk.totem_registration import TotemRegistrar, TotemRegistrationRequest
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

REGISTER_TOTEM_PROMPT = shared_config()["prompts"]["registerTotem"]


class RegisterTotemStep:
    id = "register-totem"
    title = REGISTER_TOTEM_PROMPT
    choices = ()
    interactive = True

    def __init__(
        self,
        registrar: TotemRegistrar | None = None,
    ) -> None:
        self._registrar = registrar or TotemRegistrar()

    def ask(
        self,
        ui: UI,
        context: WizardContext | None = None,
    ) -> TotemRegistrationRequest | None:
        if not ui.confirm(self.title, default=True):
            return None
        if context is None:
            return self._registrar.ask(ui)
        selection = context.require_answer(ProjectKioskStep.id)
        # The RustDesk step already asked about remote access; do not ask again here.
        request = self._registrar.ask(ui, totem_type=selection.project_type)
        skipped = RustDeskStep.id in context.answers and context.answer(RustDeskStep.id) is None
        return replace(
            request,
            screens=screens_report(build_state(context)),
            skip_rustdesk=skipped,
        )

    def apply(
        self,
        host: TotemRegistrationHost,
        registration: TotemRegistrationRequest | None,
        context: WizardContext | None = None,
    ) -> str:
        if registration is None:
            return "Done: skipped totem registration."
        progress = context.ui.progress if context is not None else None
        result = self._registrar.register_result(host, registration, progress=progress)
        if context is not None:
            context.state[self.id] = result
        return result.report

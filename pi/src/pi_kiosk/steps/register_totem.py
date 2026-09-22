from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.host import TotemRegistrationHost
from pi_kiosk.steps.project_kiosk import ProjectKioskStep
from pi_kiosk.totem_registration import TotemRegistrar, TotemRegistrationRequest
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

REGISTER_TOTEM_PROMPT = "Register this totem now?"


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
        totem_type = None
        host = None
        if context is not None:
            selection = context.require_answer(ProjectKioskStep.id)
            totem_type = selection.project_type
            host = context.host
        return self._registrar.ask(
            ui,
            totem_type=totem_type,
            host=host,
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

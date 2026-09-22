from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.host import Host
from pi_kiosk.setup_summary import render_setup_summary
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext


class SetupSummaryStep:
    id = "setup-summary"
    title = "Setup summary"
    choices = ()
    interactive = False

    def ask(self, ui: UI, context: WizardContext | None = None) -> None:
        return None

    def apply(
        self,
        host: Host,
        answer=None,
        context: WizardContext | None = None,
    ) -> str:
        if context is None:
            raise RuntimeError("Wizard context is required for the setup summary step.")
        return render_setup_summary(context)

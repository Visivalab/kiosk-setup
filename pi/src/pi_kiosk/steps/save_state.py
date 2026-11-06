from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.kiosk_state import build_state, save_state
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext


class SaveStateStep:
    """Records the applied setup (no passwords) for register-totem and the visual wizard."""

    id = "kiosk-state"
    title = "Save kiosk setup"
    choices = ()
    interactive = False

    def ask(self, ui: UI, context: WizardContext | None = None) -> None:
        return None

    def apply(self, host, answer=None, context: WizardContext | None = None) -> str:
        if context is None:
            raise RuntimeError("Wizard context is required to save the kiosk setup.")
        state = build_state(context)
        path = save_state(host, state)
        context.state[self.id] = state
        count = len(state["displays"])
        screens = "1 screen" if count == 1 else f"{count} screens"
        return f"Done: saved the kiosk setup for {screens} to {path}."

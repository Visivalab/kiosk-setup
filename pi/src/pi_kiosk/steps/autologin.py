from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.host import AutologinHost
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext


class AutologinStep:
    id = "autologin"
    title = "Desktop autologin"
    choices = ()

    def ask(self, ui: UI, context: WizardContext | None = None) -> None:
        return None

    def apply(
        self,
        host: AutologinHost,
        answer=None,
        context: WizardContext | None = None,
    ) -> str:
        host.run(["raspi-config", "nonint", "do_boot_behaviour", "B4"], check=True)
        if context is not None:
            context.state[self.id] = host.user()
        return (
            "Done: desktop autologin is enabled. "
            "The machine will start the desktop without asking for a password. "
            "The account password still exists for sudo."
        )

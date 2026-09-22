from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.host import RustDeskHost
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext


class RustDeskStep:
    id = "rustdesk"
    title = "RustDesk password"
    choices = ()
    interactive = True

    def ask(self, ui: UI, context: WizardContext | None = None) -> str:
        while True:
            password = ui.secret(self.title).strip()
            if password:
                return password
            ui.warn("RustDesk password cannot be empty.")

    def apply(
        self,
        host: RustDeskHost,
        password: str,
        context: WizardContext | None = None,
    ) -> str:
        progress = context.ui.progress if context is not None else None
        install = host.install_rustdesk(password, progress=progress)
        if context is not None:
            context.state[self.id] = install
        return (
            "Done: RustDesk installed and configured. "
            f"ID: {install.rustdesk_id}"
        )

from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.host import RustDeskHost
from pi_kiosk.shared_config import config as shared_config
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext


RUSTDESK_INSTALL_PROMPT = "Install RustDesk for remote access?"
RUSTDESK_CONFIRM_PROMPT = "Confirm RustDesk password"
RUSTDESK_SKIPPED_KEY = "rustdesk-skipped"


def ask_confirmed_password(ui: UI, prompt: str) -> str:
    while True:
        password = ui.secret(prompt).strip()
        if not password:
            ui.warn("RustDesk password cannot be empty.")
            continue
        if ui.secret(RUSTDESK_CONFIRM_PROMPT).strip() == password:
            return password
        ui.warn("The RustDesk passwords do not match. Enter them again.")


class RustDeskStep:
    id = "rustdesk"
    title = shared_config()["prompts"]["rustdeskPassword"]
    choices = ()
    interactive = True

    def ask(self, ui: UI, context: WizardContext | None = None) -> str | None:
        if not ui.confirm(RUSTDESK_INSTALL_PROMPT, default=True):
            return None
        return ask_confirmed_password(ui, self.title)

    def apply(
        self,
        host: RustDeskHost,
        password: str | None,
        context: WizardContext | None = None,
    ) -> str:
        if password is None:
            if context is not None:
                context.state[RUSTDESK_SKIPPED_KEY] = True
            return "Done: skipped RustDesk setup; remote access will not be available."
        progress = context.ui.progress if context is not None else None
        install = host.install_rustdesk(password, progress=progress)
        if context is not None:
            context.state[self.id] = install
        return (
            "Done: RustDesk installed and configured. "
            f"ID: {install.rustdesk_id}"
        )

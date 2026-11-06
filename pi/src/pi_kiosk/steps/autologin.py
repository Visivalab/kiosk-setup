from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.desktop_session import enable_autologin, install_labwc_session
from pi_kiosk.host import AutologinHost
from pi_kiosk.machine import RASPBERRY_PI
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
        if host.platform() != RASPBERRY_PI:
            return self._apply_desktop(host, context)
        host.run(["raspi-config", "nonint", "do_boot_behaviour", "B4"], check=True)
        if context is not None:
            context.state[self.id] = host.user()
        return (
            "Done: desktop autologin is enabled. "
            "The machine will start the desktop without asking for a password. "
            "The account password still exists for sudo."
        )

    def _apply_desktop(self, host, context: WizardContext | None) -> str:
        """Ubuntu/Debian: install labwc and log the user straight into it."""
        progress = context.ui.progress if context is not None else None
        if progress is not None:
            progress("Installing labwc and its Wayland tools")
        install_labwc_session(host)
        user = host.user()
        manager = host.display_manager() or "gdm3"
        warning = enable_autologin(host, user, manager)
        if context is not None:
            context.state[self.id] = user
        report = (
            f"Done: desktop autologin into a labwc session is enabled for {user} ({manager}). "
            "Reboot to start the kiosk session. The account password still exists for sudo."
        )
        return f"{report} WARN: {warning}" if warning else report

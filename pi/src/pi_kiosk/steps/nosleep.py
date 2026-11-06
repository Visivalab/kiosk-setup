from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.files import read_or_empty, upsert_marked_block
from pi_kiosk.desktop_session import SLEEP_TARGETS
from pi_kiosk.host import NoSleepHost
from pi_kiosk.machine import RASPBERRY_PI
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

BEGIN = "# pi-kiosk-setup:nosleep-begin"
END = "# pi-kiosk-setup:nosleep-end"
IDLE_GUARD = "wlopm --on '*' >/dev/null 2>&1 || true"


class NoSleepStep:
    id = "nosleep"
    title = "Keep the display awake"
    choices = ()

    def ask(self, ui: UI, context: WizardContext | None = None) -> None:
        return None

    def apply(
        self,
        host: NoSleepHost,
        answer=None,
        context: WizardContext | None = None,
    ) -> str:
        if host.platform() == RASPBERRY_PI:
            host.run(["raspi-config", "nonint", "do_blanking", "1"], check=True)
        else:
            # labwc never blanks on its own; stop the PC itself from suspending.
            host.run(["systemctl", "mask", *SLEEP_TARGETS], check=True)

        path = f"{host.home()}/.config/labwc/autostart"
        host.mkdir(f"{host.home()}/.config/labwc")
        updated = upsert_marked_block(
            read_or_empty(host, path),
            BEGIN,
            END,
            IDLE_GUARD,
        )
        host.write_file(path, updated)
        if context is not None:
            context.state[self.id] = True

        return (
            "Done: screen blanking and sleep are disabled. "
            "The display should stay on after reboot."
        )

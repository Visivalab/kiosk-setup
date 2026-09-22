from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.choice import Choice
from pi_kiosk.display import DISPLAY_CONFIG_KEY, DisplayConfig
from pi_kiosk.files import read_or_empty, upsert_marked_block
from pi_kiosk.host import RotationHost
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

ROTATION_CHOICES = (
    Choice("none", "No rotation"),
    Choice("clockwise", "Rotate clockwise (90°)"),
    Choice("counterclockwise", "Rotate counterclockwise (90°)"),
)

_TRANSFORMS = {
    "none": "normal",
    "clockwise": "270",
    "counterclockwise": "90",
}

_LABELS = {choice.id: choice.label for choice in ROTATION_CHOICES}

BEGIN = "# pi-kiosk-setup:rotation-begin"
END = "# pi-kiosk-setup:rotation-end"
DEFAULT_OUTPUT = "HDMI-A-1"


def transform_for(choice_id: str) -> str:
    try:
        return _TRANSFORMS[choice_id]
    except KeyError as exc:
        raise ValueError(f"unknown rotation choice: {choice_id}") from exc


class RotationStep:
    id = "rotation"
    title = "Screen rotation"
    choices = ROTATION_CHOICES

    def ask(self, ui: UI, context: WizardContext | None = None) -> str:
        return ui.choose(self.title, list(self.choices))

    def apply(
        self,
        host: RotationHost,
        choice_id: str,
        context: WizardContext | None = None,
    ) -> str:
        transform = transform_for(choice_id)
        output = host.detect_wayland_output() or DEFAULT_OUTPUT
        command = f"wlr-randr --output {output} --transform {transform}"

        path = f"{host.home()}/.config/labwc/autostart"
        host.mkdir(f"{host.home()}/.config/labwc")
        updated = upsert_marked_block(
            read_or_empty(host, path),
            BEGIN,
            END,
            command,
        )
        host.write_file(path, updated)
        live_result = host.run_in_desktop_session(
            ["wlr-randr", "--output", output, "--transform", transform],
            check=False,
        )
        applied_live = getattr(live_result, "returncode", 1) == 0
        if context is not None:
            context.state[DISPLAY_CONFIG_KEY] = DisplayConfig(
                output=output,
                transform=transform,
                choice_id=choice_id,
                applied_live=applied_live,
            )

        label = _LABELS[choice_id]
        if applied_live:
            return (
                f"Done: screen rotation set to {label.lower()} "
                f"({command}) and applied live. It will persist on future graphical logins."
            )
        return (
            f"Done: screen rotation set to {label.lower()} "
            f"({command}). It applies on the next graphical login."
        )

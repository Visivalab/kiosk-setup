from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.choice import Choice
from pi_kiosk.display import (
    DISPLAY_CONFIG_KEY,
    DISPLAY_CONFIGS_KEY,
    DisplayConfig,
    display_label,
)
from pi_kiosk.files import read_or_empty, upsert_marked_block
from pi_kiosk.host import RotationHost, WaylandOutput
from pi_kiosk.shared_config import config as shared_config
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

_ROTATION_LABELS = shared_config()["choices"]["rotation"]
ROTATION_CHOICES = (
    Choice("none", _ROTATION_LABELS["none"]),
    Choice("clockwise", _ROTATION_LABELS["clockwise"]),
    Choice("counterclockwise", _ROTATION_LABELS["counterclockwise"]),
    Choice("upside-down", _ROTATION_LABELS["upside-down"]),
)

_TRANSFORMS = {
    "none": "normal",
    "clockwise": "270",
    "counterclockwise": "90",
    "upside-down": "180",
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


def rotation_prompt(title: str, number: int, output: WaylandOutput) -> str:
    return f"{title} - {display_label(number, output)}"


def multi_display_command(
    outputs: list[WaylandOutput],
    rotations: dict[str, str],
) -> list[str]:
    """One wlr-randr call for every screen, placed left to right after rotation."""
    argv = ["wlr-randr"]
    x = 0
    sizes_known = all(output.width and output.height for output in outputs)
    for output in outputs:
        transform = transform_for(rotations[output.name])
        argv += ["--output", output.name, "--transform", transform]
        if sizes_known:
            argv += ["--pos", f"{x},0"]
            portrait = transform in ("90", "270")
            x += output.height if portrait else output.width
    return argv


class RotationStep:
    id = "rotation"
    title = shared_config()["prompts"]["screenRotation"]
    choices = ROTATION_CHOICES

    def ask(self, ui: UI, context: WizardContext | None = None) -> str | dict[str, str]:
        displays = context.displays() if context is not None else []
        if len(displays) <= 1:
            return ui.choose(self.title, list(self.choices))
        return {
            output.name: ui.choose(rotation_prompt(self.title, number, output), list(self.choices))
            for number, output in enumerate(displays, start=1)
        }

    def apply(
        self,
        host: RotationHost,
        choice_id: str | dict[str, str],
        context: WizardContext | None = None,
    ) -> str:
        if isinstance(choice_id, dict):
            return self._apply_many(host, choice_id, context)
        transform = transform_for(choice_id)
        output = host.detect_wayland_output() or DEFAULT_OUTPUT
        command = f"wlr-randr --output {output} --transform {transform}"

        self._write_autostart(host, command)
        live_result = host.run_in_desktop_session(
            ["wlr-randr", "--output", output, "--transform", transform],
            check=False,
        )
        applied_live = getattr(live_result, "returncode", 1) == 0
        if context is not None:
            config = DisplayConfig(
                output=output,
                transform=transform,
                choice_id=choice_id,
                applied_live=applied_live,
            )
            context.state[DISPLAY_CONFIG_KEY] = config
            context.state[DISPLAY_CONFIGS_KEY] = [config]

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

    def _apply_many(
        self,
        host: RotationHost,
        rotations: dict[str, str],
        context: WizardContext | None,
    ) -> str:
        detected = context.displays() if context is not None else host.detect_wayland_outputs()
        by_name = {output.name: output for output in detected}
        outputs = [by_name.get(name, WaylandOutput(name=name)) for name in rotations]
        argv = multi_display_command(outputs, rotations)
        command = " ".join(argv)
        self._write_autostart(host, command)
        live_result = host.run_in_desktop_session(argv, check=False)
        applied_live = getattr(live_result, "returncode", 1) == 0
        configs = [
            DisplayConfig(
                output=name,
                transform=transform_for(choice),
                choice_id=choice,
                applied_live=applied_live,
            )
            for name, choice in rotations.items()
        ]
        if context is not None:
            context.state[DISPLAY_CONFIGS_KEY] = configs
            context.state[DISPLAY_CONFIG_KEY] = configs[0]
        details = ", ".join(f"{name} {_LABELS[choice].lower()}" for name, choice in rotations.items())
        when = (
            "applied live. It will persist on future graphical logins."
            if applied_live
            else "It applies on the next graphical login."
        )
        return f"Done: screen rotation set on {len(configs)} displays ({details}); {when}"

    def _write_autostart(self, host: RotationHost, command: str) -> None:
        path = f"{host.home()}/.config/labwc/autostart"
        host.mkdir(f"{host.home()}/.config/labwc")
        updated = upsert_marked_block(
            read_or_empty(host, path),
            BEGIN,
            END,
            command,
        )
        host.write_file(path, updated)

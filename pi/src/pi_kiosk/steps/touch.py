from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pi_kiosk.choice import Choice
from pi_kiosk.display import (
    DISPLAY_CONFIG_KEY,
    DISPLAY_CONFIGS_KEY,
    DisplayConfig,
    choice_id_for_transform,
    display_title,
)
from pi_kiosk.files import normalize_labwc_rc_xml, read_or_empty
from pi_kiosk.host import TouchHost
from pi_kiosk.steps.rotation import BEGIN as ROTATION_BEGIN
from pi_kiosk.steps.rotation import END as ROTATION_END
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

TOUCH_DISPLAY_PROMPT = "Which display has the touchscreen?"
BEGIN = "<!-- pi-kiosk-setup:touch-begin -->"
END = "<!-- pi-kiosk-setup:touch-end -->"
_RC_XML_HEADER = '<?xml version="1.0"?>\n<labwc_config>\n'
_RC_XML_FOOTER = "</labwc_config>\n"
_TRANSFORM_LABELS = {
    "normal": "no rotation",
    "90": "counterclockwise rotation",
    "180": "180 degree rotation",
    "270": "clockwise rotation",
}
_CALIBRATION_MATRICES = {
    "90": "0 -1 1 1 0 0",
    "180": "-1 0 1 0 -1 1",
    "270": "0 1 0 -1 0 1",
}


@dataclass(frozen=True)
class TouchResult:
    touchscreen_detected: bool
    mapping_updated: bool
    rotation_label: str = ""
    output: str = ""


class TouchStep:
    id = "touch"
    title = "Touchscreen mapping"
    choices = ()

    def ask(self, ui: UI, context: WizardContext | None = None) -> str | None:
        if context is None:
            return None
        displays = context.displays()
        if len(displays) <= 1 or not context.host.touchscreen_present():
            return None
        options = [
            Choice(id=output.name, label=display_title(number, output))
            for number, output in enumerate(displays, start=1)
        ]
        return ui.choose(TOUCH_DISPLAY_PROMPT, options)

    def apply(
        self,
        host: TouchHost,
        answer: str | None = None,
        context: WizardContext | None = None,
    ) -> str:
        if not host.touchscreen_present():
            if context is not None:
                context.state[self.id] = TouchResult(
                    touchscreen_detected=False,
                    mapping_updated=False,
                )
            return "Done: no touch screen was detected. Nothing was changed."

        multiple = answer is not None
        display_config = _display_config(host, context, answer)
        output = display_config.output
        transform = display_config.transform
        if transform == "normal" and not multiple:
            if context is not None:
                context.state[self.id] = TouchResult(
                    touchscreen_detected=True,
                    mapping_updated=False,
                )
            return (
                "Done: touch screen detected. No mapping needed because the screen is not rotated."
            )

        matrix = _CALIBRATION_MATRICES.get(transform)
        path = f"{host.home()}/.config/labwc/rc.xml"
        host.mkdir(f"{host.home()}/.config/labwc")
        updated = upsert_touch_block(
            read_or_empty(host, path),
            output=output,
            matrix=matrix,
        )
        host.write_file(path, updated)
        if context is not None:
            context.state[self.id] = TouchResult(
                touchscreen_detected=True,
                mapping_updated=True,
                rotation_label=_TRANSFORM_LABELS[transform],
                output=output if multiple else "",
            )
        if multiple:
            return (
                f"Done: touch screen detected. Touch input was mapped to {output} "
                f"with {_TRANSFORM_LABELS[transform]}."
            )
        return (
            "Done: touch screen detected. Touch mapping was updated to match "
            f"{_TRANSFORM_LABELS[transform]}."
        )


def _display_config(
    host: TouchHost,
    context: WizardContext | None,
    output: str | None = None,
) -> DisplayConfig:
    if context is not None and output is not None:
        for candidate in context.state.get(DISPLAY_CONFIGS_KEY, []):
            if candidate.output == output:
                return candidate
        return DisplayConfig(output=output, transform="normal", choice_id="none")
    if context is not None:
        candidate = context.state.get(DISPLAY_CONFIG_KEY)
        if isinstance(candidate, DisplayConfig):
            return candidate

    output, transform = _read_rotation_state(host)
    config = DisplayConfig(
        output=output,
        transform=transform,
        choice_id=choice_id_for_transform(transform),
    )
    if context is not None:
        context.state[DISPLAY_CONFIG_KEY] = config
    return config


def _read_rotation_state(host: TouchHost) -> tuple[str, str]:
    path = f"{host.home()}/.config/labwc/autostart"
    content = read_or_empty(host, path)
    if ROTATION_BEGIN not in content or ROTATION_END not in content:
        return "HDMI-A-1", "normal"
    _, rest = content.split(ROTATION_BEGIN, 1)
    block, _ = rest.split(ROTATION_END, 1)
    parts = block.split()
    try:
        output = parts[parts.index("--output") + 1]
        transform = parts[parts.index("--transform") + 1]
    except (ValueError, IndexError):
        return "HDMI-A-1", "normal"
    return output, transform


def touch_block(output: str, matrix: str | None) -> str:
    lines = ["  <touch mapToOutput=\"%s\" />" % output]
    if matrix:
        lines += [
            "  <libinput>",
            "    <device category=\"touch\">",
            f"      <calibrationMatrix>{matrix}</calibrationMatrix>",
            "    </device>",
            "  </libinput>",
        ]
    return "\n".join(lines)


def upsert_touch_block(original: str, *, output: str, matrix: str | None) -> str:
    original = normalize_labwc_rc_xml(original)
    block = f"{BEGIN}\n{touch_block(output, matrix)}\n{END}"
    if not original.strip():
        return f"{_RC_XML_HEADER}{block}\n{_RC_XML_FOOTER}"
    if BEGIN in original and END in original:
        pre, rest = original.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        if post.startswith("\n"):
            post = post[1:]
        return f"{pre}{block}\n{post}"
    closing = "</labwc_config>"
    if closing in original:
        before, after = original.rsplit(closing, 1)
        if before and not before.endswith("\n"):
            before += "\n"
        return f"{before}{block}\n{closing}{after}"
    if original and not original.endswith("\n"):
        original += "\n"
    return f"{original}{block}\n"

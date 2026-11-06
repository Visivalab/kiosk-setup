from __future__ import annotations

import re
from dataclasses import dataclass

from pi_kiosk.host import WaylandOutput

_MODE = re.compile(r"^(\d+)x(\d+) px")

_CHOICE_IDS_BY_TRANSFORM = {
    "normal": "none",
    "90": "counterclockwise",
    "270": "clockwise",
}


@dataclass(frozen=True)
class DisplayConfig:
    output: str
    transform: str
    choice_id: str = ""
    applied_live: bool = False


def choice_id_for_transform(transform: str) -> str:
    return _CHOICE_IDS_BY_TRANSFORM.get(transform, "")


DISPLAY_CONFIG_KEY = "display_config"
DISPLAY_CONFIGS_KEY = "display_configs"


def display_label(number: int, output: WaylandOutput) -> str:
    detail = f" {output.description}" if output.description else ""
    return f"display {number} ({output.name}{detail})"


def display_title(number: int, output: WaylandOutput) -> str:
    label = display_label(number, output)
    return label[0].upper() + label[1:]


def parse_wlr_randr(stdout: str) -> list[WaylandOutput]:
    """Enabled outputs from plain `wlr-randr` text, in the order it lists them."""
    outputs: list[WaylandOutput] = []
    current: dict | None = None

    def finish() -> None:
        if current is not None and current["enabled"]:
            outputs.append(
                WaylandOutput(
                    name=current["name"],
                    description=current["description"],
                    width=current["width"],
                    height=current["height"],
                )
            )

    for line in stdout.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            finish()
            name, _, rest = line.partition(" ")
            description = rest.strip().strip('"')
            suffix = f"({name})"
            if description.endswith(suffix):
                description = description[: -len(suffix)].strip()
            if description.startswith("(null)"):
                description = ""
            current = {"name": name, "description": description, "enabled": True, "width": 0, "height": 0}
            continue
        if current is None:
            continue
        text = line.strip()
        if text.startswith("Enabled:"):
            current["enabled"] = text.split(":", 1)[1].strip() == "yes"
        match = _MODE.match(text)
        if match and "current" in text:
            current["width"] = int(match.group(1))
            current["height"] = int(match.group(2))
    finish()
    return outputs

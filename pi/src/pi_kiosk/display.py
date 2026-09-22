from __future__ import annotations

from dataclasses import dataclass

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

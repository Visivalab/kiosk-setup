"""What the wizard configured, saved so later runs can reuse it.

`register-totem` reads it to report every screen without asking again, and the
visual wizard pre-fills its form from it. It never contains passwords.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pi_kiosk.files import read_or_empty

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

KIOSK_STATE_PATH = "/etc/pi-kiosk/kiosk-state.json"
STATE_VERSION = 1
WEBAPP_PORT = 8080
DEFAULT_OUTPUT = "HDMI-A-1"


def build_state(context: WizardContext) -> dict[str, Any]:
    """Describe the planned setup from the wizard answers (before or after applying)."""
    from pi_kiosk.steps.project_kiosk import ProjectKioskStep
    from pi_kiosk.steps.rotation import RotationStep
    from pi_kiosk.steps.rustdesk import RustDeskStep
    from pi_kiosk.steps.touch import TouchStep

    selection = context.answer(ProjectKioskStep.id)
    project_type = getattr(selection, "project_type", "") or ""
    request = getattr(selection, "request", None)
    rotation = context.answer(RotationStep.id)
    screens = list(getattr(request, "screens", ()) or ())

    displays: list[dict[str, Any]] = []
    if screens:
        rotations = rotation if isinstance(rotation, dict) else {}
        for number, screen in enumerate(screens, start=1):
            displays.append(
                {
                    "number": number,
                    "output": screen.output,
                    "rotation": rotations.get(screen.output, "none"),
                    "type": "video",
                    "source": screen.source.shared_url,
                    "audio": bool(screen.audio),
                }
            )
    else:
        detected = context.displays()
        output = detected[0].name if detected else DEFAULT_OUTPUT
        if isinstance(rotation, dict):
            output, rotation = next(iter(rotation.items()), (output, "none"))
        source = getattr(request, "source", None)
        source_label = getattr(source, "shared_url", None) or getattr(source, "release_url", "")
        displays.append(
            {
                "number": 1,
                "output": output,
                "rotation": rotation if isinstance(rotation, str) else "none",
                "type": project_type,
                "source": _source_path(project_type, source_label),
                "audio": True,
            }
        )

    audio_display = next((item["output"] for item in displays if item["audio"]), "")
    return {
        "version": STATE_VERSION,
        "projectType": project_type,
        "displays": displays,
        "audioDisplay": audio_display,
        "audioDevice": getattr(request, "audio_device", "") or "",
        "audioDeviceName": getattr(request, "audio_device_name", "") or "",
        "touchOutput": context.answer(TouchStep.id) or "",
        "skipRustDesk": RustDeskStep.id in context.answers and context.answer(RustDeskStep.id) is None,
    }


def _source_path(project_type: str, source: str) -> str:
    """Keep the S3 path the user typed, not the full URL, so the form shows the same text."""
    if project_type != "webapp":
        return source
    from pi_kiosk.steps.webapp_kiosk import S3_RELEASE_BASE_URL

    return source[len(S3_RELEASE_BASE_URL):] if source.startswith(S3_RELEASE_BASE_URL) else source


def save_state(host, state: dict[str, Any]) -> str:
    saved = dict(state)
    saved["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    host.mkdir(KIOSK_STATE_PATH.rsplit("/", 1)[0])
    host.write_file(KIOSK_STATE_PATH, json.dumps(saved, indent=2) + "\n")
    return KIOSK_STATE_PATH


def load_state(host) -> dict[str, Any] | None:
    try:
        text = read_or_empty(host, KIOSK_STATE_PATH)
    except OSError:
        return None
    if not text.strip():
        return None
    try:
        state = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return None
    if not isinstance(state.get("displays"), list) or not state["displays"]:
        return None
    return state


def screens_report(state: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Screens in the shape the backend already receives from Windows totems."""
    return tuple(
        {
            "number": int(item.get("number", index)),
            "deviceName": str(item.get("output", "")),
            "type": str(item.get("type", "")),
            "rotation": str(item.get("rotation", "none")),
            "source": str(item.get("source", "")),
            "port": WEBAPP_PORT if item.get("type") == "webapp" else 0,
            "audio": bool(item.get("audio", False)),
        }
        for index, item in enumerate(state.get("displays", []), start=1)
    )


def state_totem_type(state: dict[str, Any]) -> str:
    return str(state.get("projectType") or state["displays"][0].get("type") or "video")


def detected_state(outputs, totem_type: str) -> dict[str, Any]:
    """A state for a Pi that was never configured: every detected screen, one type."""
    names = [output.name for output in outputs] or [DEFAULT_OUTPUT]
    return {
        "version": STATE_VERSION,
        "projectType": totem_type,
        "displays": [
            {"number": number, "output": name, "rotation": "none", "type": totem_type, "source": "", "audio": number == 1}
            for number, name in enumerate(names, start=1)
        ],
    }

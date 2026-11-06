"""Turns the visual wizard's form into the same answers the terminal wizard collects.

All validation happens here, before anything is applied, so a bad link on the
second screen cannot leave the first one half-configured (same rule as Windows).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pi_kiosk.display import display_title
from pi_kiosk.kiosk_state import build_state, load_state, screens_report
from pi_kiosk.shared_config import config as shared_config
from pi_kiosk.steps.kiosk_common import CLOSE, REBOOT, SIMULATE_AUTORUN
from pi_kiosk.steps.project_kiosk import (
    DEFAULT_AUDIO_OUTPUT_LABEL,
    PROJECT_TYPE_CHOICES,
    ProjectKioskStep,
    ProjectSelection,
)
from pi_kiosk.steps.register_totem import RegisterTotemStep
from pi_kiosk.steps.rotation import ROTATION_CHOICES, RotationStep
from pi_kiosk.steps.rustdesk import RustDeskStep
from pi_kiosk.steps.touch import TouchStep
from pi_kiosk.steps.video_kiosk import VideoKioskRequest, VideoScreen, local_video_problem
from pi_kiosk.steps.video_kiosk import normalize_source as normalize_video_source
from pi_kiosk.steps.webapp_kiosk import WebAppKioskRequest
from pi_kiosk.steps.webapp_kiosk import normalize_source as normalize_webapp_source
from pi_kiosk.totem_registration import TotemRegistrationRequest

FINAL_ACTIONS = {"launch": SIMULATE_AUTORUN, "reboot": REBOOT, "nothing": CLOSE}
ROTATIONS = {choice.id for choice in ROTATION_CHOICES}
PROJECT_TYPES = {choice.id for choice in PROJECT_TYPE_CHOICES}


class FormError(ValueError):
    """A form answer is invalid. Nothing has been changed."""


def build_hello(host) -> dict[str, Any]:
    """Everything the window needs to draw itself, sent once when it opens."""
    shared = shared_config()
    outputs = host.detect_wayland_outputs()
    displays = []
    for number, output in enumerate(outputs, start=1):
        size = f" - {output.width}x{output.height}" if output.width and output.height else ""
        displays.append(
            {
                "name": output.name,
                "label": f"{display_title(number, output)}{size}",
            }
        )
    return {
        "type": "hello",
        "platform": host.platform(),
        "user": host.user(),
        "home": host.home(),
        "displays": displays,
        "audioOutputs": [{"id": item.id, "name": item.name} for item in host.audio_outputs()],
        "defaultAudioLabel": DEFAULT_AUDIO_OUTPUT_LABEL,
        "touchscreen": bool(host.touchscreen_present()),
        "rotations": [{"id": choice.id, "label": choice.label} for choice in ROTATION_CHOICES],
        "projects": [{"id": choice.id, "label": choice.label} for choice in PROJECT_TYPE_CHOICES],
        "webappExample": shared["webappPathExample"],
        "state": load_state(host),
    }


def form_to_answers(form: dict[str, Any], host) -> dict[str, Any]:
    """Validate the whole form and return answers keyed by wizard step id."""
    from pi_kiosk.wizard_context import WizardContext

    detected = [output.name for output in host.detect_wayland_outputs()]
    entries = list(form.get("displays") or [])
    if not entries:
        raise FormError("No active displays were detected.")
    if [str(entry.get("output", "")) for entry in entries] != detected:
        raise FormError("The connected displays changed since the wizard opened. Nothing was changed.")
    multiple = len(entries) > 1

    sources = []
    for number, entry in enumerate(entries, start=1):
        label = f"Display {number}"
        if entry.get("rotation") not in ROTATIONS:
            raise FormError(f"{label} needs a screen rotation.")
        kind = entry.get("type")
        if kind not in PROJECT_TYPES:
            raise FormError(f"{label} needs a kiosk type.")
        if multiple and kind != "video":
            raise FormError(f"Multiple displays can only run video kiosks. {label} is set to webapp.")
        text = str(entry.get("source", ""))
        try:
            source = normalize_webapp_source(text) if kind == "webapp" else normalize_video_source(text)
        except ValueError as exc:
            raise FormError(f"{label} - {exc}") from exc
        problem = local_video_problem(host, source) if kind == "video" else None
        if problem:
            raise FormError(f"{label} - {problem[0].lower()}{problem[1:]}")
        sources.append((str(entry["output"]), kind, source))

    rustdesk = None if form.get("skipRustDesk") else rustdesk_password_from_form(form)

    action = FINAL_ACTIONS.get(str(form.get("finalAction", "")))
    if action is None:
        raise FormError("Choose what to do after setup.")

    if multiple:
        audio_display = str(form.get("audioDisplay", ""))
        if audio_display not in detected:
            raise FormError("Choose which video the audio comes from.")
        audio_device = str(form.get("audioDevice", ""))
        devices = {item.id: item.name for item in host.audio_outputs()}
        if audio_device and audio_device not in devices:
            raise FormError("The chosen audio output is no longer available.")
        screens = tuple(
            VideoScreen(output=name, source=source, audio=name == audio_display)
            for name, _, source in sources
        )
        selection = ProjectSelection(
            project_type="video",
            request=VideoKioskRequest(
                source=screens[0].source,
                screens=screens,
                audio_device=audio_device,
                audio_device_name=devices.get(audio_device, ""),
            ),
        )
        rotation: str | dict[str, str] = {
            str(entry["output"]): str(entry["rotation"]) for entry in entries
        }
    else:
        _, kind, source = sources[0]
        request = WebAppKioskRequest(source=source) if kind == "webapp" else VideoKioskRequest(source=source)
        selection = ProjectSelection(project_type=kind, request=request)
        rotation = str(entries[0]["rotation"])

    touch = None
    if multiple and host.touchscreen_present():
        touch = str(form.get("touchOutput", ""))
        if touch not in detected:
            raise FormError("Choose which display has the touchscreen.")

    answers: dict[str, Any] = {
        RotationStep.id: rotation,
        TouchStep.id: touch,
        RustDeskStep.id: rustdesk,
        ProjectKioskStep.id: selection,
        RegisterTotemStep.id: None,
        "next-action": action,
    }

    if form.get("registerTotem"):
        registration = registration_from_form(form, selection.project_type)
        context = WizardContext(host=host, ui=None)
        for step_id, answer in answers.items():
            context.record_answer(step_id, answer)
        answers[RegisterTotemStep.id] = replace(
            registration,
            screens=screens_report(build_state(context)),
            skip_rustdesk=rustdesk is None,
        )
    return answers


def rustdesk_password_from_form(form: dict[str, Any], missing: str = "") -> str:
    password = str(form.get("rustdeskPassword", "")).strip()
    if not password:
        raise FormError(missing or "Enter a RustDesk password, or check Skip RustDesk.")
    if str(form.get("rustdeskPasswordConfirm", "")).strip() != password:
        raise FormError("The RustDesk passwords do not match.")
    return password


def registration_from_form(form: dict[str, Any], totem_type: str) -> TotemRegistrationRequest:
    name = str(form.get("totemName", "")).strip()
    if not name:
        raise FormError("Enter a totem name or turn off registration.")
    return TotemRegistrationRequest(
        totem_type=totem_type,
        totem_name=name,
        description=str(form.get("totemDescription", "")).strip(),
        location=str(form.get("totemLocation", "")).strip(),
    )

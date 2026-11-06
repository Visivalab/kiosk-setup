"""Root side of the visual wizard: runs what the window asks for and streams progress.

The window (gui.py) runs as the desktop user and never touches the system.
It sends one JSON request per button; this session answers with `log` events
while working and one `done` event at the end.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from pi_kiosk.app import Wizard
from pi_kiosk.choice import Choice
from pi_kiosk.cleanup import run_cleanup
from pi_kiosk.gui_model import (
    FormError,
    form_to_answers,
    registration_from_form,
    rustdesk_password_from_form,
)
from pi_kiosk.kiosk_state import detected_state, load_state, screens_report, state_totem_type
from pi_kiosk.totem_registration import TotemRegistrar

Emit = Callable[[dict[str, Any]], None]
DONE_MESSAGES = {
    "configure": "Kiosk setup finished.",
    "register": "Totem registered.",
    "cleanup": "Kiosk setup removed.",
}


class EventUI:
    """UI that forwards progress to the window. Nothing is asked while applying."""

    def __init__(self, emit: Emit) -> None:
        self._emit = emit

    def _log(self, text: str) -> None:
        self._emit({"type": "log", "text": text})

    def progress(self, message: str) -> None:
        self._log(f"[....] {message}")

    def info(self, message: str) -> None:
        self._log(message)

    def warn(self, message: str) -> None:
        self._log(f"WARN: {message}")

    def _no_questions(self, *args, **kwargs):
        raise RuntimeError("The visual wizard cannot ask questions while applying.")

    def choose(self, prompt: str, options: list[Choice]) -> str:
        return self._no_questions()

    prompt = secret = confirm = _no_questions


class GuiSession:
    def __init__(self, host, emit: Emit) -> None:
        self.host = host
        self.emit = emit
        self.ui = EventUI(emit)

    def handle(self, request: dict[str, Any]) -> None:
        kind = str(request.get("type", ""))
        handlers = {
            "configure": lambda: self._configure(request.get("form") or {}),
            "register": lambda: self._register(request.get("form") or {}),
            "cleanup": self._cleanup,
        }
        try:
            if kind not in handlers:
                raise FormError(f"Unknown request: {kind}")
            handlers[kind]()
        except Exception as exc:  # The window must always get an answer.
            message = str(exc) or exc.__class__.__name__
            self.emit({"type": "done", "request": kind, "ok": False, "message": message})
            return
        self.emit({"type": "done", "request": kind, "ok": True, "message": DONE_MESSAGES[kind]})

    def _configure(self, form: dict[str, Any]) -> None:
        answers = form_to_answers(form, self.host)
        self.ui.info("All answers are valid. Applying the setup...")
        Wizard(self.host, self.ui).apply_answers(answers)

    def _register(self, form: dict[str, Any]) -> None:
        registrar = TotemRegistrar()
        if registrar.config() is None:
            raise FormError("Totem registration is not configured.")
        state = load_state(self.host)
        if state is not None:
            self.ui.info(f"Reusing the kiosk setup saved on this Pi: {len(state['displays'])} screen(s).")
            totem_type = state_totem_type(state)
        else:
            totem_type = str(form.get("totemType") or "")
            if totem_type not in ("webapp", "video"):
                raise FormError("This Pi has no saved kiosk setup. Choose the kiosk type first.")
            state = detected_state(self.host.detect_wayland_outputs(), totem_type)
        registration = registration_from_form(form, totem_type)
        skip = bool(form.get("skipRustDesk")) or bool(state.get("skipRustDesk"))
        registration = replace(registration, screens=screens_report(state), skip_rustdesk=skip)
        if not skip:
            registration = self._with_rustdesk_setup(registration, form)
        self.ui.info(registrar.register(self.host, registration, progress=self.ui.progress))

    def _with_rustdesk_setup(self, registration, form: dict[str, Any]):
        """Same choice as the terminal register-totem: never send missing credentials silently."""
        installed = self.host.rustdesk_installed()
        if installed and self.host.connection_details().rustdesk_password:
            return registration
        password = rustdesk_password_from_form(
            form,
            missing=(
                "RustDesk is not configured on this Pi. Enter its password to set it up, "
                "or check Skip RustDesk to register without remote access."
            ),
        )
        self.ui.info(
            "Setting the RustDesk password before registering."
            if installed
            else "Installing RustDesk before registering."
        )
        return replace(registration, install_rustdesk=not installed, rustdesk_password=password)

    def _cleanup(self) -> None:
        run_cleanup(self.host, progress=self.ui.info)

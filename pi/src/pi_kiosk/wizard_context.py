from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pi_kiosk.host import Host, WaylandOutput
from pi_kiosk.ui import UI


@dataclass
class WizardContext:
    host: Host
    ui: UI
    answers: dict[str, Any] = field(default_factory=dict)
    reports: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)

    def displays(self) -> list[WaylandOutput]:
        """Connected screens, detected once per wizard run so every step sees the same list."""
        if "_displays" not in self.state:
            detect = getattr(self.host, "detect_wayland_outputs", None)
            self.state["_displays"] = list(detect()) if detect is not None else []
        return list(self.state["_displays"])

    def record_answer(self, step_id: str, answer: Any) -> None:
        self.answers[step_id] = answer

    def answer(self, step_id: str) -> Any:
        return self.answers.get(step_id)

    def require_answer(self, step_id: str) -> Any:
        if step_id not in self.answers:
            raise RuntimeError(f"Step {step_id} has not run yet.")
        return self.answers[step_id]

    def record_report(self, report: str) -> None:
        self.reports.append(report)

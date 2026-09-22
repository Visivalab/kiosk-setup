from __future__ import annotations

from typing import TYPE_CHECKING

from pi_kiosk.host import Host
from pi_kiosk.steps.project_kiosk import ProjectKioskStep
from pi_kiosk.steps.video_kiosk import VideoKioskStep
from pi_kiosk.steps.webapp_kiosk import WebAppKioskStep
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext


class FinalActionStep:
    id = "next-action"
    title = "Choose what to do next."
    choices = ()
    interactive = True

    def __init__(
        self,
        webapp_step: WebAppKioskStep | None = None,
        video_step: VideoKioskStep | None = None,
    ) -> None:
        self._steps = {
            "webapp": webapp_step or WebAppKioskStep(prompt_for_next_action=False),
            "video": video_step or VideoKioskStep(prompt_for_next_action=False),
        }

    def ask(self, ui: UI, context: WizardContext | None = None) -> str:
        current_step = self._current_step(context)
        return ui.choose(
            current_step.next_action_prompt(),
            current_step.next_action_choices(),
        )

    def apply(
        self,
        host: Host,
        action: str,
        context: WizardContext | None = None,
    ) -> str:
        return self._current_step(context).perform_next_action(host, action)

    def _current_step(
        self,
        context: WizardContext | None,
    ) -> WebAppKioskStep | VideoKioskStep:
        if context is None:
            raise RuntimeError("Wizard context is required for the final action step.")
        selection = context.require_answer(ProjectKioskStep.id)
        return self._steps[selection.project_type]

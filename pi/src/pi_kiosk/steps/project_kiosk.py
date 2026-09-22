from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pi_kiosk.choice import Choice
from pi_kiosk.host import Host, VideoSource, WebAppSource
from pi_kiosk.steps.kiosk_common import NEXT_ACTION_PROMPT
from pi_kiosk.steps.video_kiosk import VideoKioskRequest, VideoKioskStep
from pi_kiosk.steps.webapp_kiosk import WebAppKioskRequest, WebAppKioskStep
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

TYPE_OF_PROJECT_PROMPT = "Type of project"
WEBAPP = "webapp"
VIDEO = "video"
PROJECT_TYPE_CHOICES = [
    Choice(id=WEBAPP, label="Webapp"),
    Choice(id=VIDEO, label="Video"),
]


@dataclass(frozen=True)
class ProjectSelection:
    project_type: str
    request: WebAppKioskRequest | VideoKioskRequest

    @property
    def source(self) -> WebAppSource | VideoSource:
        return self.request.source

    @property
    def next_action(self) -> str | None:
        return self.request.next_action


class ProjectKioskStep:
    id = "project-kiosk"
    title = TYPE_OF_PROJECT_PROMPT
    choices = PROJECT_TYPE_CHOICES
    interactive = True

    def __init__(
        self,
        *,
        prompt_for_next_action: bool = True,
        webapp_step: WebAppKioskStep | None = None,
        video_step: VideoKioskStep | None = None,
    ) -> None:
        self._steps = {
            WEBAPP: webapp_step or WebAppKioskStep(prompt_for_next_action=prompt_for_next_action),
            VIDEO: video_step or VideoKioskStep(prompt_for_next_action=prompt_for_next_action),
        }

    def ask(
        self,
        ui: UI,
        context: WizardContext | None = None,
    ) -> ProjectSelection:
        project_type = ui.choose(self.title, list(self.choices))
        request = self._steps[project_type].ask(ui, context)
        return ProjectSelection(project_type=project_type, request=request)

    def apply(
        self,
        host: Host,
        selection: ProjectSelection,
        context: WizardContext | None = None,
    ) -> str:
        return self._steps[selection.project_type].apply(host, selection.request, context)

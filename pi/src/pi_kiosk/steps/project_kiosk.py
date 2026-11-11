from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pi_kiosk.choice import Choice
from pi_kiosk.display import display_label, display_title
from pi_kiosk.host import Host, VideoSource, WebAppSource
from pi_kiosk.shared_config import config as shared_config
from pi_kiosk.steps.kiosk_common import NEXT_ACTION_PROMPT
from pi_kiosk.steps.video_kiosk import VideoKioskRequest, VideoKioskStep, VideoScreen
from pi_kiosk.steps.webapp_kiosk import WebAppKioskRequest, WebAppKioskStep
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

_SHARED_CONFIG = shared_config()
TYPE_OF_PROJECT_PROMPT = _SHARED_CONFIG["prompts"]["projectType"]
WEBAPP = "webapp"
VIDEO = "video"
AUDIO_DISPLAY_PROMPT = "Which video plays the audio? The other screens are muted."
AUDIO_OUTPUT_PROMPT = "Audio output"
DEFAULT_AUDIO_OUTPUT_LABEL = "Speakers of the screen that plays the audio"
PROJECT_TYPE_CHOICES = [
    Choice(id=WEBAPP, label=_SHARED_CONFIG["choices"]["project"][WEBAPP]),
    Choice(id=VIDEO, label=_SHARED_CONFIG["choices"]["project"][VIDEO]),
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
        displays = context.displays() if context is not None else []
        if len(displays) > 1:
            return self._ask_many(ui, context, displays)
        project_type = ui.choose(self.title, list(self.choices))
        request = self._steps[project_type].ask(ui, context)
        return ProjectSelection(project_type=project_type, request=request)

    def _ask_many(self, ui: UI, context: WizardContext, displays) -> ProjectSelection:
        video_step: VideoKioskStep = self._steps[VIDEO]
        ui.info("Multiple displays detected. Each display gets its own looping video.")
        sources = []
        for number, output in enumerate(displays, start=1):
            prompt = f"{video_step.title} - {display_label(number, output)}"
            sources.append((output.name, video_step.ask_source(ui, context, prompt=prompt)))

        audio_display = ui.choose(
            AUDIO_DISPLAY_PROMPT,
            [
                Choice(id=output.name, label=display_title(number, output))
                for number, output in enumerate(displays, start=1)
            ],
        )
        audio_device = ""
        audio_device_name = ""
        devices = context.host.audio_outputs()
        if devices:
            audio_device = ui.choose(
                AUDIO_OUTPUT_PROMPT,
                [Choice(id="", label=DEFAULT_AUDIO_OUTPUT_LABEL)]
                + [Choice(id=device.id, label=device.name) for device in devices],
            )
            audio_device_name = next(
                (device.name for device in devices if device.id == audio_device), ""
            )
        screens = tuple(
            VideoScreen(output=name, source=source, audio=name == audio_display)
            for name, source in sources
        )
        request = VideoKioskRequest(
            source=screens[0].source,
            screens=screens,
            audio_device=audio_device,
            audio_device_name=audio_device_name,
        )
        return ProjectSelection(project_type=VIDEO, request=request)

    def apply(
        self,
        host: Host,
        selection: ProjectSelection,
        context: WizardContext | None = None,
    ) -> str:
        return self._steps[selection.project_type].apply(host, selection.request, context)

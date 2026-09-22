from __future__ import annotations

from pi_kiosk.display import DISPLAY_CONFIG_KEY, DisplayConfig, choice_id_for_transform
from pi_kiosk.host import (
    RustDeskInstall,
    VideoDeployment,
    VideoSource,
    WebAppDeployment,
    WebAppSource,
)
from pi_kiosk.steps.autologin import AutologinStep
from pi_kiosk.steps.nosleep import NoSleepStep
from pi_kiosk.steps.project_kiosk import ProjectKioskStep
from pi_kiosk.steps.register_totem import RegisterTotemStep
from pi_kiosk.steps.rustdesk import RustDeskStep
from pi_kiosk.steps.touch import TouchResult, TouchStep
from pi_kiosk.steps.video_kiosk import VideoKioskStep
from pi_kiosk.steps.webapp_kiosk import WebAppKioskStep
from pi_kiosk.totem_registration import TotemRegistrationRequest, TotemRegistrationResult
from pi_kiosk.wizard_context import WizardContext

_ROTATION_LABELS = {
    "none": "no rotation",
    "clockwise": "clockwise",
    "counterclockwise": "counterclockwise",
}


def render_setup_summary(context: WizardContext) -> str:
    lines = ["Done: setup summary", ""]
    lines.extend(_rotation_lines(context))
    lines.extend(_touch_lines(context))
    lines.extend(_nosleep_lines(context))
    lines.extend(_autologin_lines(context))
    lines.extend(_rustdesk_lines(context))
    lines.extend(_project_lines(context))
    lines.extend(_webapp_lines(context))
    lines.extend(_video_lines(context))
    lines.extend(_totem_registration_lines(context))
    return "\n".join(lines)


def _rotation_lines(context: WizardContext) -> list[str]:
    display_config = context.state.get(DISPLAY_CONFIG_KEY)
    if not isinstance(display_config, DisplayConfig):
        return []

    choice_id = display_config.choice_id or choice_id_for_transform(display_config.transform)
    label = _ROTATION_LABELS.get(choice_id, choice_id or display_config.transform)
    if display_config.applied_live:
        return [
            _checked(
                f"Screen rotation set to {label} on {display_config.output} and applied live; "
                "it will persist on future graphical logins"
            )
        ]
    return [
        _checked(
            f"Screen rotation set to {label} on {display_config.output}; "
            "it will apply on the next graphical login"
        )
    ]


def _touch_lines(context: WizardContext) -> list[str]:
    touch_result = context.state.get(TouchStep.id)
    if not isinstance(touch_result, TouchResult):
        return []
    if not touch_result.touchscreen_detected:
        return [_checked("No touch screen detected, so no touch mapping changes were needed")]
    if not touch_result.mapping_updated:
        return [
            _checked(
                "Touch screen detected, but no mapping changes were needed because the "
                "screen is not rotated"
            )
        ]
    return [_checked(f"Touch mapping was updated to match {touch_result.rotation_label}")]


def _nosleep_lines(context: WizardContext) -> list[str]:
    if context.state.get(NoSleepStep.id):
        return [_checked("Screen blanking and sleep were disabled")]
    return []


def _autologin_lines(context: WizardContext) -> list[str]:
    user = context.state.get(AutologinStep.id)
    if not isinstance(user, str) or not user:
        return []
    return [
        _checked(
            f"Desktop autologin was enabled for user {user}; the account password still works for SSH and sudo"
        )
    ]


def _rustdesk_lines(context: WizardContext) -> list[str]:
    install = context.state.get(RustDeskStep.id)
    if not isinstance(install, RustDeskInstall):
        return []
    return [
        _checked(
            f"RustDesk unattended access was installed and configured with ID {install.rustdesk_id}"
        )
    ]


def _project_lines(context: WizardContext) -> list[str]:
    selection = context.answer(ProjectKioskStep.id)
    project_type = getattr(selection, "project_type", None)
    if not isinstance(project_type, str) or not project_type:
        return []
    return [_checked(f"Project selected: {project_type}")]


def _webapp_lines(context: WizardContext) -> list[str]:
    deployment = context.state.get(WebAppKioskStep.id)
    if not isinstance(deployment, WebAppDeployment):
        return []

    source = _project_source(context, WebAppSource)
    source_label = deployment.source_url
    if source is not None:
        source_label = _format_webapp_source(source)

    lines = [_checked(f"Downloaded the webapp from {source_label}")]
    if deployment.app_dir:
        lines.append(_checked(f"Deployed the webapp to {deployment.app_dir}"))
    if deployment.launcher_path:
        lines.append(_checked(f"Wrote the kiosk launcher to {deployment.launcher_path}"))
    if deployment.autostart_configured:
        lines.append(
            _checked("Configured labwc autostart to launch the kiosk on the next graphical login")
        )
    if deployment.server_url:
        lines.append(_checked(f"Configured the local server to serve the app on {deployment.server_url}"))
    if deployment.chromium_kiosk_configured:
        lines.append(_checked("Configured Chromium kiosk mode for the deployed app"))
    if deployment.cursor_hide_configured:
        lines.append(_checked("Configured automatic mouse hide after idle"))
    if deployment.log_tail_command:
        lines.append(_checked(f"Server logs: {deployment.log_tail_command}"))
    if deployment.heartbeat_log_tail_command:
        lines.append(_checked(f"Heartbeat logs: {deployment.heartbeat_log_tail_command}"))
    return lines


def _video_lines(context: WizardContext) -> list[str]:
    deployment = context.state.get(VideoKioskStep.id)
    if not isinstance(deployment, VideoDeployment):
        return []

    lines: list[str] = []
    source = _project_source(context, VideoSource)
    if source is not None and source.shared_url:
        lines.append(_checked(f"Downloaded the video from {source.shared_url}"))
    if deployment.video_path:
        lines.append(_checked(f"Deployed the video file to {deployment.video_path}"))
    if deployment.launcher_path:
        lines.append(_checked(f"Wrote the video launcher to {deployment.launcher_path}"))
    if deployment.autostart_configured:
        lines.append(
            _checked("Configured labwc autostart to launch the video on the next graphical login")
        )
    if deployment.fullscreen_loop_configured:
        lines.append(_checked("Configured mpv for fullscreen looping playback"))
    return lines


def _totem_registration_lines(context: WizardContext) -> list[str]:
    if RegisterTotemStep.id not in context.answers:
        return []
    registration = context.answer(RegisterTotemStep.id)
    if registration is None:
        return [_checked("Totem registration was skipped")]
    if not isinstance(registration, TotemRegistrationRequest):
        return []

    result = context.state.get(RegisterTotemStep.id)
    if not isinstance(result, TotemRegistrationResult):
        return []

    message = (
        f'Registered totem "{registration.totem_name}" for machine {result.machine_name}.'
    )
    if result.detail:
        message = f"{message} {result.detail}"
    return [_checked(message)]


def _project_source(context: WizardContext, expected_type: type[WebAppSource | VideoSource]):
    selection = context.answer(ProjectKioskStep.id)
    request = getattr(selection, "request", None)
    source = getattr(request, "source", None)
    if isinstance(source, expected_type):
        return source
    return None


def _format_webapp_source(source: WebAppSource) -> str:
    return source.release_url


def _checked(message: str) -> str:
    return f"- [x] {message}"

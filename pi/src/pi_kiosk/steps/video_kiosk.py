from __future__ import annotations

import posixpath
import shlex
from dataclasses import replace
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pi_kiosk.choice import Choice
from pi_kiosk.errors import UserFacingError
from pi_kiosk.host import VideoHost, VideoSource
from pi_kiosk.shared_config import config as shared_config
from pi_kiosk.steps.kiosk_common import (
    CLOSE,
    REBOOT,
    SIMULATE_AUTORUN,
    install_kiosk_autostart,
)
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

_SHARED_CONFIG = shared_config()
DROPBOX_PROMPT = f'{_SHARED_CONFIG["prompts"]["videoSource"]} or absolute local video path'
VIDEO_SCREENS_KEY = "video-screens"
VIDEO_NEXT_ACTION_PROMPT = _SHARED_CONFIG["prompts"]["videoNextAction"]
_VIDEO_ACTION_CHOICES = _SHARED_CONFIG["choices"]["videoAction"]
VIDEO_NEXT_ACTION_CHOICES = [
    Choice(id=SIMULATE_AUTORUN, label=_VIDEO_ACTION_CHOICES["launch"]),
    Choice(id=REBOOT, label=_VIDEO_ACTION_CHOICES["reboot"]),
    Choice(id=CLOSE, label=_VIDEO_ACTION_CHOICES["nothing"]),
]


@dataclass(frozen=True)
class VideoScreen:
    output: str
    source: VideoSource
    audio: bool = False


@dataclass(frozen=True)
class VideoKioskRequest:
    source: VideoSource
    next_action: str | None = None
    screens: tuple[VideoScreen, ...] = ()
    audio_device: str = ""
    audio_device_name: str = ""


def normalize_source(value: str) -> VideoSource:
    text = value.strip()
    if not text:
        raise ValueError("Enter a Dropbox shared file link or an absolute local video path.")
    if text.startswith("/"):
        path = posixpath.normpath(text)
        return VideoSource(shared_url=path, download_url="", local_path=path)

    parsed = urlparse(text)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ValueError("Enter a valid Dropbox shared file link over HTTPS.")
    if hostname != "dropbox.com" and not hostname.endswith(".dropbox.com"):
        raise ValueError("Enter a valid Dropbox shared file link.")
    path_parts = [part for part in parsed.path.split("/") if part]
    is_shared_file = len(path_parts) >= 2 and path_parts[0] == "s"
    is_scl_file = len(path_parts) >= 3 and path_parts[0] == "scl" and path_parts[1] == "fi"
    if not (is_shared_file or is_scl_file):
        raise ValueError("Enter a valid Dropbox shared file link.")

    query = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True) if key != "dl"]
    query.append(("dl", "1"))
    download_url = urlunparse(parsed._replace(query=urlencode(query)))
    return VideoSource(shared_url=text, download_url=download_url)


def launcher_path(home: str) -> str:
    return f"{home}/.config/pi-kiosk/video-kiosk.sh"


def launcher_script(mpv: str, video_path: str) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"VIDEO_PATH={shlex.quote(video_path)}",
            f"MPV={shlex.quote(mpv)}",
            (
                '"$MPV" --fs --loop-file=inf --no-osc --no-osd-bar '
                '--cursor-autohide=always --input-touch-emulate-mouse=no "$VIDEO_PATH"'
            ),
            "",
        ]
    )


def local_video_problem(host, source: VideoSource) -> str | None:
    """Checked before anything is applied, so a bad path cannot leave a half-configured Pi."""
    if not source.local_path:
        return None
    if not host.exists(source.local_path):
        return f"Local video file not found: {source.local_path}"
    if not host.is_nonempty_file(source.local_path):
        return f"Local video is empty or not a file: {source.local_path}"
    return None


_MPV_ARGS = (
    "--fs --loop-file=inf --no-osc --no-osd-bar "
    "--cursor-autohide=always --input-touch-emulate-mouse=no"
)


def multi_launcher_script(
    mpv: str,
    players: list[tuple[str, str, bool]],
    audio_device: str = "",
) -> str:
    """One mpv per screen, each pinned to its output; only one keeps its sound."""
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"MPV={shlex.quote(mpv)}",
        f"AUDIO_DEVICE={shlex.quote(audio_device)}",
        'STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pi-kiosk"',
        'mkdir -p "$STATE_DIR"',
        "pids=()",
        "cleanup() {",
        '  if [ "${#pids[@]}" -gt 0 ]; then kill "${pids[@]}" >/dev/null 2>&1 || true; fi',
        '  rm -f "$STATE_DIR"/display-*.pid',
        "}",
        "trap cleanup EXIT",
        "trap 'exit 0' INT TERM",
        "audio_args=()",
        'if [ -n "$AUDIO_DEVICE" ]; then',
        '  sink="${AUDIO_DEVICE#pulse/}"',
        "  # A missing device falls back to the default output instead of silence.",
        '  if command -v pactl >/dev/null 2>&1 && LC_ALL=C pactl list short sinks 2>/dev/null | cut -f2 | grep -qxF "$sink"; then',
        '    audio_args=(--audio-device="$AUDIO_DEVICE")',
        "  fi",
        "fi",
        "start_player() {",
        '  local output="$1" video="$2" sound="$3"',
        '  local extra=("${audio_args[@]}")',
        '  if [ "$sound" != "yes" ]; then extra=(--no-audio); fi',
        f'  "$MPV" {_MPV_ARGS} \\',
        '    --fs-screen-name="$output" --screen-name="$output" --title="pi-kiosk-$output" \\',
        '    "${extra[@]}" "$video" &',
        '  pids+=("$!")',
        '  echo "$!" >"$STATE_DIR/display-$output.pid"',
        "}",
    ]
    for output, video_path, audio in players:
        sound = "yes" if audio else "no"
        lines.append(f"start_player {shlex.quote(output)} {shlex.quote(video_path)} {sound}")
    lines += ["wait", ""]
    return "\n".join(lines)


class VideoKioskStep:
    id = "video-kiosk"
    title = DROPBOX_PROMPT
    choices = ()
    interactive = True

    def __init__(self, *, prompt_for_next_action: bool = True) -> None:
        self._prompt_for_next_action = prompt_for_next_action

    def ask_source(
        self,
        ui: UI,
        context: WizardContext | None = None,
        prompt: str | None = None,
    ) -> VideoSource:
        while True:
            raw = ui.prompt(prompt or self.title)
            try:
                source = normalize_source(raw)
            except ValueError as exc:
                ui.warn(str(exc))
                continue
            problem = local_video_problem(context.host, source) if context is not None else None
            if problem:
                ui.warn(problem)
                continue
            return source

    def ask(
        self,
        ui: UI,
        context: WizardContext | None = None,
    ) -> VideoKioskRequest:
        while True:
            source = self.ask_source(ui, context)
            next_action = None
            if self._prompt_for_next_action:
                next_action = ui.choose(VIDEO_NEXT_ACTION_PROMPT, VIDEO_NEXT_ACTION_CHOICES)
            return VideoKioskRequest(source=source, next_action=next_action)

    def apply(
        self,
        host: VideoHost,
        request: VideoKioskRequest | VideoSource,
        context: WizardContext | None = None,
    ) -> str:
        if isinstance(request, VideoSource):
            request = VideoKioskRequest(source=request)

        progress = context.ui.progress if context is not None else None
        if len(request.screens) > 1:
            return self._apply_many(host, request, context, progress)
        deployment = host.deploy_video(request.source, progress=progress)
        mpv = self._mpv(host)

        home = host.home()
        host.mkdir(f"{home}/.config/pi-kiosk")
        host.write_file(
            launcher_path(home),
            launcher_script(mpv, deployment.video_path),
        )
        install_kiosk_autostart(host, launcher_path(home))
        if context is not None:
            context.state[self.id] = replace(
                deployment,
                launcher_path=launcher_path(home),
                autostart_configured=True,
                fullscreen_loop_configured=True,
            )

        report = (
            f"Done: video kiosk deployed with {deployment.file_name}. "
            "mpv will start on the next graphical login."
        )
        if request.next_action is not None:
            report = f"{report} {self.perform_next_action(host, request.next_action)}"
        return report

    def _mpv(self, host: VideoHost) -> str:
        mpv = host.mpv_command()
        if mpv is None:
            host.ensure_packages_installed(("mpv",))
            mpv = host.mpv_command()
        if mpv is None:
            raise UserFacingError(
                "mpv could not be prepared on this Pi. Install it and run the wizard again."
            )
        return mpv

    def _apply_many(
        self,
        host: VideoHost,
        request: VideoKioskRequest,
        context: WizardContext | None,
        progress,
    ) -> str:
        deployments = []
        for screen in request.screens:
            if progress is not None:
                progress(f"Preparing the video for {screen.output}")
            deployments.append(host.deploy_video(screen.source, progress=progress, slot=screen.output))
        mpv = self._mpv(host)

        home = host.home()
        host.mkdir(f"{home}/.config/pi-kiosk")
        players = [
            (screen.output, deployment.video_path, screen.audio)
            for screen, deployment in zip(request.screens, deployments)
        ]
        host.write_file(
            launcher_path(home),
            multi_launcher_script(mpv, players, request.audio_device),
        )
        install_kiosk_autostart(host, launcher_path(home))
        if context is not None:
            context.state[self.id] = replace(
                deployments[0],
                launcher_path=launcher_path(home),
                autostart_configured=True,
                fullscreen_loop_configured=True,
            )
            context.state[VIDEO_SCREENS_KEY] = list(zip(request.screens, deployments))

        audio = next((screen.output for screen in request.screens if screen.audio), None)
        output = request.audio_device_name or "the default output"
        audio_report = (
            f"Audio plays from {audio} through {output}; the other screens are muted."
            if audio
            else "Every screen plays muted."
        )
        names = ", ".join(
            f"{screen.output}: {deployment.file_name}" for screen, deployment in zip(request.screens, deployments)
        )
        report = (
            f"Done: video kiosk deployed on {len(deployments)} displays ({names}). "
            f"mpv will start on every screen on the next graphical login. {audio_report}"
        )
        if request.next_action is not None:
            report = f"{report} {self.perform_next_action(host, request.next_action)}"
        return report

    def next_action_prompt(self) -> str:
        return VIDEO_NEXT_ACTION_PROMPT

    def next_action_choices(self) -> list[Choice]:
        return list(VIDEO_NEXT_ACTION_CHOICES)

    def perform_next_action(self, host: VideoHost, action: str) -> str:
        if action == SIMULATE_AUTORUN:
            host.launch_video_now(launcher_path(host.home()))
            return "Done: launching video now for testing."
        if action == REBOOT:
            host.reboot()
            return "Done: rebooting now for the final production startup."
        return "Done: doing nothing now."

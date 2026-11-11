from __future__ import annotations

import html
import posixpath
from pathlib import Path
import shlex
from dataclasses import replace
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pi_kiosk import audio_route
from pi_kiosk.audio import screen_audio_output
from pi_kiosk.choice import Choice
from pi_kiosk.errors import DesktopSessionUnavailable, UserFacingError
from pi_kiosk.files import read_or_empty, upsert_labwc_rc_block
from pi_kiosk.host import VideoHost, VideoSource
from pi_kiosk.shared_config import config as shared_config
from pi_kiosk.steps.kiosk_common import (
    CLOSE,
    NO_SESSION_NOTE,
    REBOOT,
    SIMULATE_AUTORUN,
    install_kiosk_autostart,
    remove_marked_block,
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


# VLC, not mpv: Raspberry Pi maintains VLC and supports it, not mpv. On a Pi 5
# with two screens mpv stuttered while VLC, opened by hand, played both videos
# smoothly. It is the full VLC with its Qt window (as on Windows): cvlc's own
# Wayland output crashes on a Pi 5. VLC stops on an unknown option, so every
# one below exists in VLC 3.0 on any Linux build.
VLC_OPTIONS = (
    "--no-one-instance",
    "--fullscreen",
    "--repeat",
    "--no-video-title-show",
    "--no-osd",
    "--no-qt-fs-controller",
    "--mouse-hide-timeout=0",
    # A double tap on a touchscreen would leave fullscreen.
    "--no-mouse-events",
    # First-run privacy question and "continue where you left off?".
    "--no-qt-privacy-ask",
    "--qt-continue=0",
    # No resize to the video's size at the start: see "Each video on its screen".
    "--no-qt-video-autoresize",
)
_VLC_ARGS_LINE = f"VLC_ARGS=({' '.join(VLC_OPTIONS)})"

# To check the loop on the real screens without waiting for the whole video:
#   PI_KIOSK_LOOP_SECONDS=15 bash ~/.config/pi-kiosk/video-kiosk.sh
# VLC treats the stop time as the end of the file, so a day of loops fits in minutes.
_LOOP_CHECK = (
    'if [ -n "${PI_KIOSK_LOOP_SECONDS:-}" ]; then',
    '  VLC_ARGS+=(--stop-time="$PI_KIOSK_LOOP_SECONDS")',
    "fi",
)

# Nobody restarts a kiosk in an exhibition. VLC ends with 0 when a person closes
# it (or the cleanup stops it) and stays closed; any other end is a crash.
RESTART_SECONDS = 2

# The Qt window goes through XWayland, and "launch now" from the wizard runs the
# launcher with WAYLAND_DISPLAY only. Find XWayland's display in that case.
_FIND_X11_DISPLAY = (
    'if [ -z "${DISPLAY:-}" ]; then',
    '  for socket in "${PI_KIOSK_X11_DIR:-/tmp/.X11-unix}"/X*; do',
    '    if [ -S "$socket" ]; then export DISPLAY=":${socket##*/X}"; break; fi',
    "  done",
    "fi",
)

# Each video on its screen. VLC can choose it itself (--qt-fullscreen-screennumber),
# but that is an X11 move followed by a fullscreen request, and labwc applies the
# move late when the window is also changing size, and not at all before the
# window is shown. The fullscreen then lands on the screen under the pointer. On
# a Pi 4, two boots in five went wrong: the second video on the first screen
# (explained by the above) or shifted over it (not explained; the position can
# only have come from VLC). So labwc does it: a window rule moves each VLC to its screen when its window
# first appears, and VLC only asks for fullscreen. The rule tells the players
# apart by their X11 instance name, which Qt takes from RESOURCE_NAME and labwc
# matches from 0.8.1 on. An older labwc keeps VLC's own choice.
LABWC_PINS_FROM = (0, 8, 1)
SCREENS_RC_BEGIN = "<!-- pi-kiosk-setup:video-screens-begin -->"
SCREENS_RC_END = "<!-- pi-kiosk-setup:video-screens-end -->"


def rc_xml_path(home: str) -> str:
    return f"{home}/.config/labwc/rc.xml"


def window_name(output: str) -> str:
    return f"pi-kiosk-{output}"


def screen_rules(outputs: list[str]) -> str:
    lines = ["  <windowRules>"]
    for output in outputs:
        lines += [
            f'    <windowRule identifier="{html.escape(window_name(output))}">',
            f'      <action name="MoveToOutput" output="{html.escape(output)}" />',
            "    </windowRule>",
        ]
    lines.append("  </windowRules>")
    return "\n".join(lines)


def write_screen_rules(host: VideoHost, outputs: list[str]) -> None:
    """One rule per screen; with no screens, the rules of an earlier setup are removed."""
    path = rc_xml_path(host.home())
    original = read_or_empty(host, path)
    if outputs:
        host.mkdir(f"{host.home()}/.config/labwc")
        updated = upsert_labwc_rc_block(original, SCREENS_RC_BEGIN, SCREENS_RC_END, screen_rules(outputs))
    else:
        updated = remove_marked_block(original, SCREENS_RC_BEGIN, SCREENS_RC_END)
    if updated != original:
        host.write_file(path, updated)


# Where labwc cannot do it, VLC picks the fullscreen screen by number, counted
# as Qt sees XWayland's screens: in xrandr order, primary first. XWayland names
# them after the Wayland outputs (HDMI-A-1). Otherwise the wizard's order is used.
_SCREEN_NUMBER = (
    "screen_number() {",
    '  local want="$1" fallback="$2" i=0 name',
    "  while IFS= read -r name; do",
    '    if [ "$name" = "$want" ]; then echo "$i"; return; fi',
    "    i=$((i + 1))",
    "  done < <(xrandr --query 2>/dev/null \\",
    "    | awk '$2 == \"connected\" { first = ($3 == \"primary\") ? 0 : 1; print first, $1 }' \\",
    "    | sort -s -n -k1,1 | cut -d' ' -f2)",
    '  echo "$fallback"',
    "}",
)


# At boot labwc runs the launcher before PipeWire has published the HDMI
# outputs, and VLC opens its audio output only once. audio-route.py (copied
# next to the launcher) waits for the speakers, makes them the system default
# so the sound cannot go to a screen without speakers (a projector), and logs
# what it did to ~/.local/state/pi-kiosk/audio.log.
AUDIO_ROUTE_SOURCE = Path(audio_route.__file__).read_text()
AUDIO_LOG = "~/.local/state/pi-kiosk/audio.log"
_AUDIO_ROUTE_LINE = 'AUDIO_ROUTE="$(dirname "${BASH_SOURCE[0]}")/audio-route.py"'


def audio_route_path(home: str) -> str:
    return f"{home}/.config/pi-kiosk/audio-route.py"


def launcher_path(home: str) -> str:
    return f"{home}/.config/pi-kiosk/video-kiosk.sh"


def launcher_script(vlc: str, video_path: str) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"VIDEO_PATH={shlex.quote(video_path)}",
            f"VLC={shlex.quote(vlc)}",
            _VLC_ARGS_LINE,
            *_LOOP_CHECK,
            *_FIND_X11_DISPLAY,
            _AUDIO_ROUTE_LINE,
            "# Wait until the sound output exists, or VLC starts silent at boot.",
            'python3 "$AUDIO_ROUTE" >/dev/null 2>&1 || true',
            "# Started again if it crashes; closed by a person, it stays closed.",
            f'until "$VLC" "${{VLC_ARGS[@]}}" "$VIDEO_PATH"; do sleep {RESTART_SECONDS}; done',
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




def multi_launcher_script(
    vlc: str,
    players: list[tuple[str, str, bool]],
    audio_device: str = "",
    labwc_pins: bool = False,
) -> str:
    """One VLC per screen, each fullscreen on its own output; only one keeps its sound.

    With labwc_pins, labwc's window rules put each VLC on its screen and VLC is
    not given a screen number.
    """
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"VLC={shlex.quote(vlc)}",
        f"AUDIO_DEVICE={shlex.quote(audio_device)}",
        _VLC_ARGS_LINE,
        *_LOOP_CHECK,
        *_FIND_X11_DISPLAY,
        'STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pi-kiosk"',
        'mkdir -p "$STATE_DIR"',
        "pids=()",
        "cleanup() {",
        '  if [ "${#pids[@]}" -gt 0 ]; then kill "${pids[@]}" >/dev/null 2>&1 || true; fi',
        '  rm -f "$STATE_DIR"/display-*.pid',
        "}",
        "trap cleanup EXIT",
        "trap 'exit 0' INT TERM",
        *(() if labwc_pins else _SCREEN_NUMBER),
        _AUDIO_ROUTE_LINE,
        'sink=""',
    ]
    audio_screen = next((output for output, _, audio in players if audio), None)
    if audio_screen is not None:
        lines += [
            "# Finds the speakers (of this screen, or the chosen output) and makes them the",
            "# default; prints nothing if they are missing, and VLC uses the default output.",
            f'sink="$(python3 "$AUDIO_ROUTE" {shlex.quote(audio_screen)} "${{AUDIO_DEVICE#pulse/}}" 2>/dev/null || true)"',
        ]
    lines += [
        "start_player() {",
        '  local output="$1" video="$2" sound="$3" fallback="${4:-}"',
        "  # The name labwc's window rule knows this screen's VLC by.",
        '  local run=(env RESOURCE_NAME="pi-kiosk-$output") extra=(--no-audio)',
        '  if [ "$sound" = "yes" ]; then',
        "    extra=()",
        "    # An empty PULSE_SINK would name no device at all; leave it unset then.",
        '    if [ -n "$sink" ]; then run+=(PULSE_SINK="$sink"); fi',
        "  fi",
        "  # One keeper per screen: it starts VLC again if it crashes. Closed by a",
        "  # person, or stopped with this launcher, VLC stays closed.",
        "  (",
        '    player=""',
        "    stop() {",
        '      if [ -n "$player" ]; then kill "$player" >/dev/null 2>&1 || true; fi',
        "      exit 0",
        "    }",
        "    trap stop INT TERM",
        "    while :; do",
        *(
            ('      "${run[@]}" "$VLC" "${VLC_ARGS[@]}" "${extra[@]}" "$video" &',)
            if labwc_pins
            else (
                '      screen="$(screen_number "$output" "$fallback")"',
                '      "${run[@]}" "$VLC" "${VLC_ARGS[@]}" --qt-fullscreen-screennumber="$screen" \\',
                '        "${extra[@]}" "$video" &',
            )
        ),
        '      player="$!"',
        '      echo "$player" >"$STATE_DIR/display-$output.pid"',
        "      status=0",
        '      wait "$player" || status="$?"',
        '      if [ "$status" -eq 0 ]; then break; fi',
        f"      sleep {RESTART_SECONDS}",
        "    done",
        "  ) &",
        '  pids+=("$!")',
        "}",
    ]
    for number, (output, video_path, audio) in enumerate(players):
        sound = "yes" if audio else "no"
        fallback = "" if labwc_pins else f" {number}"
        lines.append(f"start_player {shlex.quote(output)} {shlex.quote(video_path)} {sound}{fallback}")
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
        vlc = self._vlc(host)

        home = host.home()
        host.mkdir(f"{home}/.config/pi-kiosk")
        host.write_file(audio_route_path(home), AUDIO_ROUTE_SOURCE)
        host.write_file(
            launcher_path(home),
            launcher_script(vlc, deployment.video_path),
        )
        write_screen_rules(host, [])
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
            "VLC will start on the next graphical login."
        )
        if request.next_action is not None:
            report = f"{report} {self.perform_next_action(host, request.next_action)}"
        return report

    def _vlc(self, host: VideoHost) -> str:
        vlc = host.vlc_command()
        if vlc is None:
            host.ensure_packages_installed(("vlc",))
            vlc = host.vlc_command()
        if vlc is None:
            raise UserFacingError(
                "VLC could not be prepared on this Pi. Install it and run the wizard again."
            )
        return vlc

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
        vlc = self._vlc(host)

        home = host.home()
        host.mkdir(f"{home}/.config/pi-kiosk")
        host.write_file(audio_route_path(home), AUDIO_ROUTE_SOURCE)
        players = [
            (screen.output, deployment.video_path, screen.audio)
            for screen, deployment in zip(request.screens, deployments)
        ]
        audio = next((screen.output for screen in request.screens if screen.audio), None)
        labwc = host.labwc_version()
        labwc_pins = labwc is not None and labwc >= LABWC_PINS_FROM
        host.write_file(
            launcher_path(home),
            multi_launcher_script(vlc, players, request.audio_device, labwc_pins),
        )
        # Written for any labwc: an older one never matches them, and they are
        # already there after an upgrade.
        write_screen_rules(host, [screen.output for screen in request.screens])
        install_kiosk_autostart(host, launcher_path(home))
        if context is not None:
            context.state[self.id] = replace(
                deployments[0],
                launcher_path=launcher_path(home),
                autostart_configured=True,
                fullscreen_loop_configured=True,
            )
            context.state[VIDEO_SCREENS_KEY] = list(zip(request.screens, deployments))

        audio_report = self._audio_report(host, request, audio)
        names = ", ".join(
            f"{screen.output}: {deployment.file_name}" for screen, deployment in zip(request.screens, deployments)
        )
        if labwc_pins:
            screens_report = "labwc keeps each video on its screen."
        else:
            found = "labwc " + ".".join(map(str, labwc)) if labwc else "this labwc"
            needed = ".".join(map(str, LABWC_PINS_FROM))
            screens_report = (
                f"WARNING - screens: {found} cannot keep each video on its screen "
                f"(needs {needed}); VLC chooses the screen itself, which can fail at boot."
            )
        report = (
            f"Done: video kiosk deployed on {len(deployments)} displays ({names}). "
            f"VLC will start on every screen on the next graphical login. {screens_report} {audio_report}"
        )
        if request.next_action is not None:
            report = f"{report} {self.perform_next_action(host, request.next_action)}"
        return report

    def _audio_report(self, host: VideoHost, request: VideoKioskRequest, audio: str | None) -> str:
        """Tells the person at the Pi where the sound will go, so a wrong output is visible."""
        if audio is None:
            return "Every screen plays muted."
        log = f"Details at every start: {AUDIO_LOG}."
        if request.audio_device:
            output = request.audio_device_name or request.audio_device
            return f"Sound: from {audio} through {output}; the other screens are muted. {log}"
        speakers = screen_audio_output(audio, host.audio_outputs())
        if speakers is not None:
            return (
                f"Sound: through the speakers of {audio} ({speakers.name}); "
                f"the other screens are muted. {log}"
            )
        return (
            f"WARNING - sound: the speakers of {audio} are not visible right now "
            "(is that screen on, with its sound enabled?). The kiosk looks for them again "
            "at every start; if they are still missing the sound goes to the system default "
            f"output, which can be the other screen. {log}"
        )

    def next_action_prompt(self) -> str:
        return VIDEO_NEXT_ACTION_PROMPT

    def next_action_choices(self) -> list[Choice]:
        return list(VIDEO_NEXT_ACTION_CHOICES)

    def perform_next_action(self, host: VideoHost, action: str) -> str:
        if action == SIMULATE_AUTORUN:
            try:
                host.launch_video_now(launcher_path(host.home()))
            except DesktopSessionUnavailable as exc:
                return f"Done: video not launched now. {exc} {NO_SESSION_NOTE}"
            return "Done: launching video now for testing."
        if action == REBOOT:
            host.reboot()
            return "Done: rebooting now for the final production startup."
        return "Done: doing nothing now."

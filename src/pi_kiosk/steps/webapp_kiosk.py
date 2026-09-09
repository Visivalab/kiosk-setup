from __future__ import annotations

import shlex
from dataclasses import replace
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from pi_kiosk.choice import Choice
from pi_kiosk.errors import UserFacingError
from pi_kiosk.host import WebAppHost, WebAppSource
from pi_kiosk.steps.kiosk_common import (
    CLOSE,
    CURSOR_RC_BEGIN,
    KIOSK_AUTOSTART_BEGIN,
    NEXT_ACTION_CHOICES,
    NEXT_ACTION_PROMPT,
    REBOOT,
    SIMULATE_AUTORUN,
    install_cursor_keybind,
    install_kiosk_autostart,
)
from pi_kiosk.totem_status import status_config_path, status_script_path
from pi_kiosk.ui import UI

if TYPE_CHECKING:
    from pi_kiosk.wizard_context import WizardContext

KIOSK_PORT = 8080
CURSOR_IDLE_SECONDS = 5
SERVER_READY_RETRIES = 50
SERVER_READY_DELAY_SECONDS = 0.2
STARTUP_HEARTBEAT_RETRIES = 12
STARTUP_HEARTBEAT_DELAY_SECONDS = 5
RELEASE_URL_PROMPT = "Webapp ZIP URL"
_GITHUB_HOSTS = {"github.com", "www.github.com"}
_HIDE_CURSOR_COMMAND = "-M alt -M logo -P h >/dev/null 2>&1 || true"
_WEBAPP_URL_EXAMPLE = (
    "https://example-bucket.s3.eu-west-3.amazonaws.com/app/app-dist.zip"
)


@dataclass(frozen=True)
class WebAppKioskRequest:
    source: WebAppSource
    next_action: str | None = None


def action_url() -> str:
    return f"http://127.0.0.1:{KIOSK_PORT}"


def log_path(home: str) -> str:
    return f"{home}/.local/state/pi-kiosk/webapp-server.log"


def log_tail_command(home: str) -> str:
    return f"tail -f {shlex.quote(log_path(home))}"


def heartbeat_log_path(home: str) -> str:
    return f"{home}/.local/state/pi-kiosk/webapp-heartbeat.log"


def heartbeat_log_tail_command(home: str) -> str:
    return f"tail -f {shlex.quote(heartbeat_log_path(home))}"


def _source_label(source: WebAppSource) -> str:
    return source.release_url


def normalize_source(value: str) -> WebAppSource:
    text = value.strip()
    if not text:
        raise ValueError(_release_url_error())

    if "://" not in text and text.lower().startswith(("github.com/", "www.github.com/")):
        text = f"https://{text}"

    parsed = urlsplit(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(_release_url_error())

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.hostname.lower() not in _GITHUB_HOSTS:
        if not parts or not parts[-1].lower().endswith(".zip"):
            raise ValueError(_release_url_error())
        return WebAppSource(
            release_url=urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        )

    if not _looks_like_release_download_path(parts):
        raise ValueError(_release_url_error())

    asset_name = parts[5]
    if not asset_name.lower().endswith(".zip"):
        raise ValueError(_release_url_error())

    normalized_path = "/".join(parts)
    return WebAppSource(release_url=f"https://github.com/{normalized_path}")


def _looks_like_release_download_path(parts: list[str]) -> bool:
    if len(parts) != 6:
        return False
    if parts[2:4] == ["releases", "download"]:
        return True
    return parts[2:5] == ["releases", "latest", "download"]


def _release_url_error() -> str:
    return f"Enter a public HTTPS webapp ZIP URL, for example {_WEBAPP_URL_EXAMPLE}."


def launcher_path(home: str) -> str:
    return f"{home}/.config/pi-kiosk/webapp-kiosk.sh"


def launcher_script(browser: str, app_dir: str, wtype: str, swayidle: str) -> str:
    quoted_dir = shlex.quote(app_dir)
    quoted_browser = shlex.quote(browser)
    quoted_wtype = shlex.quote(wtype)
    quoted_swayidle = shlex.quote(swayidle)
    quoted_status_reporter = shlex.quote(str(status_script_path()))
    quoted_status_config = shlex.quote(str(status_config_path()))
    url = f"http://127.0.0.1:{KIOSK_PORT}"
    idle_command = (
        f"{quoted_swayidle} timeout {CURSOR_IDLE_SECONDS} "
        f"'{quoted_wtype} {_HIDE_CURSOR_COMMAND}' >/dev/null 2>&1 &"
    )
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"APP_DIR={quoted_dir}",
            f"URL={shlex.quote(url)}",
            'MODE="${1:-kiosk}"',
            'LOG_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/pi-kiosk"',
            'LOG_FILE="$LOG_ROOT/webapp-server.log"',
            'HEARTBEAT_LOG_FILE="$LOG_ROOT/webapp-heartbeat.log"',
            'idle_pid=""',
            'status_reporter_pid=""',
            'mkdir -p "$LOG_ROOT"',
            ': >>"$HEARTBEAT_LOG_FILE"',
            'cd "$APP_DIR"',
            f'python3 -m http.server {KIOSK_PORT} --bind 127.0.0.1 >"$LOG_FILE" 2>&1 &',
            'server_pid="$!"',
            'cleanup() {',
            '  kill "$server_pid" >/dev/null 2>&1 || true',
            '  if [ -n "$idle_pid" ]; then',
            '    kill "$idle_pid" >/dev/null 2>&1 || true',
            '  fi',
            '  if [ -n "$status_reporter_pid" ]; then',
            '    wait "$status_reporter_pid" >/dev/null 2>&1 || true',
            '  fi',
            '}',
            'trap cleanup EXIT',
            'server_ready=0',
            'attempt=0',
            f'while [ "$server_ready" -eq 0 ] && [ "$attempt" -lt {SERVER_READY_RETRIES} ]; do',
            "  if python3 -c \"import socket, sys; sock = socket.socket(); sock.settimeout(0.2); code = sock.connect_ex(('127.0.0.1', 8080)); sock.close(); sys.exit(0 if code == 0 else 1)\" >/dev/null 2>&1; then",
            '    server_ready=1',
            "    break",
            "  fi",
            f"  sleep {SERVER_READY_DELAY_SECONDS}",
            '  attempt=$((attempt + 1))',
            "done",
            'if [ "$server_ready" -eq 1 ]; then',
            f'  if [ -x {quoted_status_reporter} ] && [ -r {quoted_status_config} ]; then',
            '    (',
            '      heartbeat_attempt=1',
            f'      while [ "$heartbeat_attempt" -le {STARTUP_HEARTBEAT_RETRIES} ]; do',
            '        printf "[%s] startup heartbeat attempt %s begin\\n" "$(date -Is)" "$heartbeat_attempt"',
            f'        if {quoted_status_reporter} {quoted_status_config}; then',
            '          printf "[%s] startup heartbeat ok on attempt %s\\n" "$(date -Is)" "$heartbeat_attempt"',
            '          exit 0',
            "        fi",
            '        status="$?"',
            '        printf "[%s] startup heartbeat attempt %s failed with exit %s\\n" "$(date -Is)" "$heartbeat_attempt" "$status"',
            f'        if [ "$heartbeat_attempt" -lt {STARTUP_HEARTBEAT_RETRIES} ]; then',
            f'          sleep {STARTUP_HEARTBEAT_DELAY_SECONDS}',
            "        fi",
            '        heartbeat_attempt=$((heartbeat_attempt + 1))',
            "      done",
            '      printf "[%s] startup heartbeat exhausted retries\\n" "$(date -Is)"',
            '      exit "$status"',
            '    ) >>"$HEARTBEAT_LOG_FILE" 2>&1 &',
            '    status_reporter_pid="$!"',
            "  else",
            '    printf "[%s] startup heartbeat skipped: reporter script or config is missing\\n" "$(date -Is)" >>"$HEARTBEAT_LOG_FILE"',
            "  fi",
            "else",
            '  printf "[%s] startup heartbeat skipped: local server was not ready after waiting\\n" "$(date -Is)" >>"$HEARTBEAT_LOG_FILE"',
            "fi",
            'if [ "$MODE" = "server-only" ]; then',
            '  wait "$server_pid"',
            "  exit 0",
            "fi",
            f"if [ -x {quoted_wtype} ]; then",
            f"  (sleep 1; {quoted_wtype} {_HIDE_CURSOR_COMMAND}) &",
            "fi",
            f"if [ -x {quoted_wtype} ] && [ -x {quoted_swayidle} ]; then",
            f"  {idle_command}",
            '  idle_pid="$!"',
            "fi",
            f'{quoted_browser} --kiosk --incognito --noerrdialogs --disable-infobars "$URL"',
            "",
        ]
    )

class WebAppKioskStep:
    id = "webapp-kiosk"
    title = RELEASE_URL_PROMPT
    choices = ()
    interactive = True

    def __init__(self, *, prompt_for_next_action: bool = True) -> None:
        self._prompt_for_next_action = prompt_for_next_action

    def ask(
        self,
        ui: UI,
        context: WizardContext | None = None,
    ) -> WebAppKioskRequest:
        while True:
            raw = ui.prompt(self.title)
            try:
                source = normalize_source(raw)
            except ValueError as exc:
                ui.warn(str(exc))
                continue

            next_action = None
            if self._prompt_for_next_action:
                next_action = ui.choose(NEXT_ACTION_PROMPT, NEXT_ACTION_CHOICES)
            return WebAppKioskRequest(source=source, next_action=next_action)

    def apply(
        self,
        host: WebAppHost,
        request: WebAppKioskRequest | WebAppSource,
        context: WizardContext | None = None,
    ) -> str:
        if isinstance(request, WebAppSource):
            request = WebAppKioskRequest(source=request)

        progress = context.ui.progress if context is not None else None
        deployment = host.deploy_webapp(request.source, progress=progress)
        browser = host.chromium_command()
        if browser is None:
            raise UserFacingError(
                "Chromium was not found on this Pi. Install Chromium and run the wizard again."
            )
        wtype = host.wtype_command()
        swayidle = host.swayidle_command()
        if wtype is None or swayidle is None:
            host.ensure_packages_installed(("wtype", "swayidle"))
            wtype = host.wtype_command()
            swayidle = host.swayidle_command()
        if wtype is None or swayidle is None:
            raise UserFacingError(
                "wtype and swayidle could not be prepared on this Pi. "
                "Install those packages and run the wizard again."
            )

        home = host.home()
        host.mkdir(f"{home}/.config/pi-kiosk")
        host.write_file(
            launcher_path(home),
            launcher_script(browser, deployment.app_dir, wtype, swayidle),
        )

        install_kiosk_autostart(host, launcher_path(home))
        install_cursor_keybind(host)
        if context is not None:
            context.state[self.id] = replace(
                deployment,
                launcher_path=launcher_path(home),
                server_url=action_url(),
                log_tail_command=log_tail_command(home),
                heartbeat_log_tail_command=heartbeat_log_tail_command(home),
                autostart_configured=True,
                chromium_kiosk_configured=True,
                cursor_hide_configured=True,
            )

        log_report = (
            "Attach a terminal to the server logs with: "
            f"{log_tail_command(home)}. "
            "Inspect startup heartbeat logs with: "
            f"{heartbeat_log_tail_command(home)}."
        )
        report = (
            f"Done: webapp kiosk deployed from {_source_label(request.source)}. "
            f"Deployed it to {deployment.app_dir}. "
            f"Chromium will start "
            f"on the next graphical login. The mouse cursor will hide after idle. "
            f"{log_report}"
        )
        if request.next_action is not None:
            report = f"{report} {self.perform_next_action(host, request.next_action)}"
        return report

    def next_action_prompt(self) -> str:
        return NEXT_ACTION_PROMPT

    def next_action_choices(self) -> list[Choice]:
        return list(NEXT_ACTION_CHOICES)

    def perform_next_action(self, host: WebAppHost, action: str) -> str:
        home = host.home()
        log_report = (
            "Attach a terminal to the server logs with: "
            f"{log_tail_command(home)}. "
            "Inspect startup heartbeat logs with: "
            f"{heartbeat_log_tail_command(home)}."
        )
        if action == SIMULATE_AUTORUN:
            host.launch_kiosk_now(launcher_path(home))
            return (
                "Done: simulated autorun for testing. Cursor may not automatically hide "
                f"until the next graphical login. The app is on {action_url()}. {log_report}"
            )
        if action == REBOOT:
            host.reboot()
            return f"Done: rebooting now for the final production startup. {log_report}"

        host.launch_webapp_server_now(launcher_path(home))
        return (
            f"Done: the app is live on {action_url()} without opening Chromium. {log_report}"
        )

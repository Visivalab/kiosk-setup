"""`sudo ./kiosk.sh gui`: open the visual wizard on the Pi desktop.

Like the Windows wizard, the window and the privileged work are separate
processes. This root process opens the window as the desktop user (so it can
reach the user's display), then runs each request the window sends and
streams the progress back over a pipe. Passwords only travel over that pipe.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TextIO

from pi_kiosk.errors import UserFacingError
from pi_kiosk.gui_model import build_hello
from pi_kiosk.gui_session import GuiSession

FRONTEND = Path(__file__).with_name("gui.py")
X11_SOCKET = Path("/tmp/.X11-unix/X0")
NO_DESKTOP = (
    "No graphical desktop session was found for {user}. Open a terminal on the Pi desktop "
    "and run the command there, or use the terminal wizard: sudo ./kiosk.sh"
)


def frontend_environment(
    environ: dict[str, str],
    session_env: dict[str, str] | None,
    x11_socket: bool,
) -> dict[str, str] | None:
    """Variables the window needs. Tk draws through X11 (Xwayland under labwc)."""
    display = environ.get("DISPLAY") or (":0" if x11_socket else "")
    if not display:
        return None
    env = dict(session_env or {})
    env["DISPLAY"] = display
    if environ.get("XAUTHORITY"):
        env["XAUTHORITY"] = environ["XAUTHORITY"]
    return env


def run_gui(host, stderr: TextIO | None = None) -> int:
    stderr = stderr if stderr is not None else sys.stderr
    if not host.is_raspberry_pi():
        print("This tool only configures Raspberry Pi OS. Nothing was changed on this machine.", file=stderr)
        return 2
    if not host.is_root():
        print("Run this tool with sudo. Nothing was changed.", file=stderr)
        return 1
    try:
        user = host.user()
    except Exception as exc:
        print(str(exc), file=stderr)
        return 1

    env = frontend_environment(dict(os.environ), host._desktop_session_env(), X11_SOCKET.exists())
    if env is None:
        print(NO_DESKTOP.format(user=user), file=stderr)
        return 1

    try:
        _ensure_tkinter(user, env, stderr)
    except UserFacingError as exc:
        print(str(exc), file=stderr)
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="pi-kiosk-gui-"))
    try:
        # The checkout may live in root's private temp dir; give the user a readable copy.
        workdir.chmod(0o755)
        frontend = workdir / "gui.py"
        shutil.copyfile(FRONTEND, frontend)
        frontend.chmod(0o644)
        return _serve(host, user, env, frontend, stderr)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _ensure_tkinter(user: str, env: dict[str, str], stderr: TextIO) -> None:
    probe = _as_user(user, env, ["python3", "-c", "import tkinter"])
    if subprocess.run(probe, capture_output=True).returncode == 0:
        return
    print("[....] Installing python3-tk for the visual wizard", file=stderr)
    if subprocess.run(["apt-get", "install", "-y", "python3-tk"]).returncode != 0:
        raise UserFacingError(
            "python3-tk could not be installed. Use the terminal wizard: sudo ./kiosk.sh"
        )


def _as_user(user: str, env: dict[str, str], argv: list[str]) -> list[str]:
    return ["sudo", "-u", user, "env", *[f"{key}={value}" for key, value in env.items()], *argv]


def _serve(host, user: str, env: dict[str, str], frontend: Path, stderr: TextIO) -> int:
    process = subprocess.Popen(
        _as_user(user, env, ["python3", str(frontend)]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None and process.stdout is not None

    def send(event: dict) -> None:
        try:
            process.stdin.write(json.dumps(event) + "\n")
            process.stdin.flush()
        except BrokenPipeError:
            pass

    # Progress is also echoed to the terminal that started the wizard.
    def emit(event: dict) -> None:
        if event.get("type") == "log":
            print(event["text"], file=stderr, flush=True)
        send(event)

    send(build_hello(host))
    session = GuiSession(host, emit)
    for line in process.stdout:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if request.get("type") == "quit":
            break
        session.handle(request)

    try:
        process.stdin.close()
    except BrokenPipeError:
        pass
    code = process.wait()
    if code not in (0, None):
        print(
            "The visual wizard window could not be opened. "
            "Use the terminal wizard instead: sudo ./kiosk.sh",
            file=stderr,
        )
        return 1
    return 0

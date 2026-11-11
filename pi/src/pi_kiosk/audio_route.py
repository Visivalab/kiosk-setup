"""Sends the kiosk sound to the right speakers. Runs as the desktop user at every kiosk start.

The setup copies this file on its own next to the launcher, so it must stay
Python 3 stdlib only, with no pi_kiosk imports.

    python3 audio-route.py [SCREEN] [OUTPUT]

SCREEN is the Wayland output whose video plays the sound (HDMI-A-1). OUTPUT is
an output name chosen in the wizard; empty means the speakers of SCREEN. It
waits until PipeWire shows that output (at boot the HDMI outputs appear a few
seconds after the desktop), makes it the system default so the sound cannot
drift to another screen (a projector without speakers), and prints its name
for the player (the launcher passes it to VLC as PULSE_SINK). It prints
nothing if it was not found.
Without arguments it only waits for any output. Each run rewrites audio.log.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

WAIT_TRIES = 40  # x 0.5 s = 20 s
POLL_SECONDS = 0.5


def run_command(argv: list[str]) -> str | None:
    """stdout of a command, or None if it is missing or failed."""
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def parse_pw_dump(text: str) -> list[dict] | None:
    """Audio sinks from `pw-dump`; None if the text is not pw-dump output."""
    try:
        objects = json.loads(text)
    except ValueError:
        return None
    if not isinstance(objects, list):
        return None
    sinks = []
    for item in objects:
        if not isinstance(item, dict) or item.get("type") != "PipeWire:Interface:Node":
            continue
        props = (item.get("info") or {}).get("props") or {}
        if props.get("media.class") != "Audio/Sink" or not props.get("node.name"):
            continue
        if props["node.name"] == "auto_null":
            continue
        sinks.append(
            {
                "id": item.get("id"),
                "name": str(props["node.name"]),
                "description": str(props.get("node.description") or props["node.name"]),
                "card": str(props.get("alsa.card_name") or props.get("api.alsa.card.name") or ""),
            }
        )
    return sinks


def parse_pactl_sinks(text: str) -> list[dict]:
    """Audio sinks from `LC_ALL=C pactl list sinks`."""
    sinks: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if raw.startswith("Sink #"):
            sinks.append({"id": None, "name": "", "description": "", "card": ""})
        elif not sinks:
            continue
        elif line.startswith("Name:"):
            sinks[-1]["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Description:"):
            sinks[-1]["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("alsa.card_name ="):
            sinks[-1]["card"] = line.split("=", 1)[1].strip().strip('"')
    for sink in sinks:
        sink["description"] = sink["description"] or sink["name"]
    return [sink for sink in sinks if sink["name"] and sink["name"] != "auto_null"]


def list_sinks(run=None) -> list[dict]:
    """pw-dump ships with PipeWire; pactl (pulseaudio-utils) is not always installed."""
    run = run or run_command
    dump = run(["pw-dump"])
    if dump is not None:
        sinks = parse_pw_dump(dump)
        if sinks:
            return sinks
    listing = run(["pactl", "list", "sinks"])
    return parse_pactl_sinks(listing) if listing is not None else []


def screen_cards(screen: str) -> set[str]:
    """On a Pi the screen HDMI-A-1 is the sound card vc4-hdmi-0, HDMI-A-2 is vc4-hdmi-1."""
    match = re.fullmatch(r"HDMI-A-(\d+)", screen or "")
    if not match:
        return set()
    port = int(match.group(1)) - 1
    return {f"vc4-hdmi-{port}", f"vc4hdmi{port}"}


def pick(sinks: list[dict], screen: str, wanted: str) -> dict | None:
    if wanted:
        return next((sink for sink in sinks if sink["name"] == wanted), None)
    cards = screen_cards(screen)
    return next((sink for sink in sinks if sink["card"] in cards), None)


def set_default(sink: dict, run=None) -> bool:
    run = run or run_command
    if sink.get("id") is not None and run(["wpctl", "set-default", str(sink["id"])]) is not None:
        return True
    return run(["pactl", "set-default-sink", sink["name"]]) is not None


def route(screen: str = "", wanted: str = "", run=None, sleep=None) -> tuple[dict | None, list[dict], bool]:
    """(chosen sink or None, sinks seen last, whether it became the default)."""
    run = run or run_command
    sleep = sleep or time.sleep
    routing = bool(screen or wanted)
    sinks: list[dict] = []
    for attempt in range(WAIT_TRIES):
        sinks = list_sinks(run)
        target = pick(sinks, screen, wanted) if routing else None
        if target is not None:
            return target, sinks, set_default(target, run)
        if not routing and sinks:
            break
        if attempt < WAIT_TRIES - 1:
            sleep(POLL_SECONDS)
    return None, sinks, False


def report(screen: str, wanted: str, target: dict | None, sinks: list[dict], is_default: bool) -> str:
    lines = [
        f"time: {datetime.now().isoformat(timespec='seconds')}",
        f"screen with sound: {screen or '-'}",
        f"output chosen in the wizard: {wanted or 'the speakers of that screen'}",
        "outputs found:",
    ]
    lines += [f"  {sink['name']} ({sink['description']}; card {sink['card'] or '-'})" for sink in sinks] or ["  none"]
    if target is not None:
        lines.append(f"sound goes to: {target['name']}")
        lines.append(f"made the system default: {'yes' if is_default else 'NO'}")
    elif screen or wanted:
        lines.append("sound goes to: NOT FOUND - VLC uses the system default output")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    screen = argv[0] if len(argv) > 0 else ""
    wanted = argv[1] if len(argv) > 1 else ""
    target, sinks, is_default = route(screen, wanted)
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "pi-kiosk"
    try:
        state.mkdir(parents=True, exist_ok=True)
        (state / "audio.log").write_text(report(screen, wanted, target, sinks, is_default))
    except OSError:
        pass
    if target is not None:
        print(target["name"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

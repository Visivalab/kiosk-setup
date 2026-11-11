from __future__ import annotations

import re

from pi_kiosk.host import AudioOutput


def parse_pactl_sinks(stdout: str) -> list[AudioOutput]:
    """Playback devices from `LC_ALL=C pactl list sinks`, as mpv --audio-device values."""
    sinks: list[dict[str, str]] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if raw.startswith("Sink #"):
            sinks.append({})
        elif not sinks:
            continue
        elif line.startswith("Name:"):
            sinks[-1]["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Description:"):
            sinks[-1]["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("alsa.card_name ="):
            sinks[-1]["card"] = line.split("=", 1)[1].strip().strip('"')

    outputs: list[AudioOutput] = []
    for sink in sinks:
        name = sink.get("name")
        if not name:
            continue
        label = sink.get("description") or name
        if sink.get("card"):
            label = f"{label} - {sink['card']}"
        outputs.append(AudioOutput(id=f"pulse/{name}", name=label, card=sink.get("card", "")))
    return outputs


def screen_audio_output(screen: str, outputs: list[AudioOutput]) -> AudioOutput | None:
    """The sound output of a Pi screen's own HDMI port (its built-in speakers).

    On a Pi the screen HDMI-A-1 is the ALSA card vc4-hdmi-0, HDMI-A-2 is vc4-hdmi-1.
    """
    match = re.fullmatch(r"HDMI-A-(\d+)", screen)
    if not match:
        return None
    port = int(match.group(1)) - 1
    cards = {f"vc4-hdmi-{port}", f"vc4hdmi{port}"}
    return next((output for output in outputs if output.card in cards), None)

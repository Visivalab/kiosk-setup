from __future__ import annotations

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
        outputs.append(AudioOutput(id=f"pulse/{name}", name=label))
    return outputs

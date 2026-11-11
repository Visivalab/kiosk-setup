from __future__ import annotations

from pi_kiosk.audio_route import parse_pactl_sinks as _parse_pactl_sinks
from pi_kiosk.audio_route import screen_cards
from pi_kiosk.host import AudioOutput


def sinks_to_outputs(sinks: list[dict]) -> list[AudioOutput]:
    """Sinks found by audio_route.list_sinks, as "pulse/<sink name>" ids."""
    outputs = []
    for sink in sinks:
        label = sink["description"] or sink["name"]
        if sink["card"]:
            label = f"{label} - {sink['card']}"
        outputs.append(AudioOutput(id=f"pulse/{sink['name']}", name=label, card=sink["card"]))
    return outputs


def parse_pactl_sinks(stdout: str) -> list[AudioOutput]:
    """Playback devices from `LC_ALL=C pactl list sinks`, as "pulse/<sink name>" ids."""
    return sinks_to_outputs(_parse_pactl_sinks(stdout))


def screen_audio_output(screen: str, outputs: list[AudioOutput]) -> AudioOutput | None:
    """The sound output of a Pi screen's own HDMI port (its built-in speakers)."""
    cards = screen_cards(screen)
    return next((output for output in outputs if output.card and output.card in cards), None)

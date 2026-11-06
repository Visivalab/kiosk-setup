import unittest

from pi_kiosk.audio import parse_pactl_sinks
from pi_kiosk.display import parse_wlr_randr
from pi_kiosk.host import AudioOutput, WaylandOutput

TWO_SCREENS = """\
HDMI-A-1 "Samsung Electric Company S24F350 H4ZN100000 (HDMI-A-1)"
  Make: Samsung Electric Company
  Model: S24F350
  Enabled: yes
  Modes:
    720x400 px, 70.081001 Hz
    1920x1080 px, 60.000000 Hz (preferred, current)
  Position: 0,0
  Transform: normal
HDMI-A-2 "Dell Inc. DELL P2419H (HDMI-A-2)"
  Enabled: yes
  Modes:
    1280x720 px, 60.000000 Hz (current)
    1920x1080 px, 60.000000 Hz (preferred)
  Position: 1920,0
  Transform: normal
DSI-1 "(null) (null) (DSI-1)"
  Enabled: no
  Modes:
    800x480 px, 60.000000 Hz (preferred)
"""

PACTL_SINKS = """\
Sink #47
\tState: SUSPENDED
\tName: alsa_output.platform-fef00700.hdmi.hdmi-stereo
\tDescription: Built-in Audio Digital Stereo (HDMI)
\tProperties:
\t\talsa.card_name = "vc4-hdmi-0"
Sink #48
\tState: SUSPENDED
\tName: alsa_output.platform-fef05700.hdmi.hdmi-stereo
\tDescription: Built-in Audio Digital Stereo (HDMI)
\tProperties:
\t\talsa.card_name = "vc4-hdmi-1"
Sink #49
\tName: bluez_output.00_11_22
\tDescription: Speaker
"""


class ParseWlrRandrTests(unittest.TestCase):
    def test_lists_enabled_outputs_with_current_mode(self):
        self.assertEqual(
            parse_wlr_randr(TWO_SCREENS),
            [
                WaylandOutput(
                    name="HDMI-A-1",
                    description="Samsung Electric Company S24F350 H4ZN100000",
                    width=1920,
                    height=1080,
                ),
                WaylandOutput(
                    name="HDMI-A-2",
                    description="Dell Inc. DELL P2419H",
                    width=1280,
                    height=720,
                ),
            ],
        )

    def test_empty_output_means_no_screens(self):
        self.assertEqual(parse_wlr_randr(""), [])


class ParsePactlSinksTests(unittest.TestCase):
    def test_lists_sinks_as_mpv_pulse_devices_and_disambiguates_hdmi_ports(self):
        self.assertEqual(
            parse_pactl_sinks(PACTL_SINKS),
            [
                AudioOutput(
                    id="pulse/alsa_output.platform-fef00700.hdmi.hdmi-stereo",
                    name="Built-in Audio Digital Stereo (HDMI) - vc4-hdmi-0",
                ),
                AudioOutput(
                    id="pulse/alsa_output.platform-fef05700.hdmi.hdmi-stereo",
                    name="Built-in Audio Digital Stereo (HDMI) - vc4-hdmi-1",
                ),
                AudioOutput(id="pulse/bluez_output.00_11_22", name="Speaker"),
            ],
        )


if __name__ == "__main__":
    unittest.main()

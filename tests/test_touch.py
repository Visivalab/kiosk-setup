import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.display import DisplayConfig
from pi_kiosk.steps.rotation import RotationStep
from pi_kiosk.steps.touch import BEGIN, TouchStep, upsert_touch_block
from pi_kiosk.wizard_context import WizardContext


class TouchStepTests(unittest.TestCase):
    def test_reports_when_no_touchscreen_is_detected(self):
        host = FakeHost()

        report = TouchStep().apply(host)

        self.assertIn("no touch screen", report.lower())
        self.assertNotIn("/home/pi/.config/labwc/rc.xml", host.files)

    def test_reports_no_mapping_needed_when_screen_is_not_rotated(self):
        host = FakeHost(touchscreen=True)
        RotationStep().apply(host, "none")

        report = TouchStep().apply(host)

        self.assertIn("no mapping needed", report.lower())
        self.assertNotIn("/home/pi/.config/labwc/rc.xml", host.files)

    def test_writes_touch_mapping_when_screen_is_rotated(self):
        host = FakeHost(touchscreen=True)
        RotationStep().apply(host, "clockwise")

        report = TouchStep().apply(host)

        content = host.files["/home/pi/.config/labwc/rc.xml"]
        self.assertIn(BEGIN, content)
        self.assertIn('<touch mapToOutput="HDMI-A-1" />', content)
        self.assertIn("<calibrationMatrix>0 1 0 -1 0 1</calibrationMatrix>", content)
        self.assertIn("clockwise", report.lower())

    def test_replaces_previous_touch_block_without_duplication(self):
        host = FakeHost(
            touchscreen=True,
            files={
                "/home/pi/.config/labwc/rc.xml": (
                    '<?xml version="1.0"?>\n'
                    "<labwc_config>\n"
                    "  <keyboard />\n"
                    f"{BEGIN}\n"
                    '  <touch mapToOutput="HDMI-A-1" />\n'
                    "  <libinput>\n"
                    '    <device category="touch">\n'
                    "      <calibrationMatrix>old</calibrationMatrix>\n"
                    "    </device>\n"
                    "  </libinput>\n"
                    "<!-- pi-kiosk-setup:touch-end -->\n"
                    "</labwc_config>\n"
                )
            },
        )
        RotationStep().apply(host, "counterclockwise")

        TouchStep().apply(host)

        content = host.files["/home/pi/.config/labwc/rc.xml"]
        self.assertIn("  <keyboard />", content)
        self.assertEqual(content.count(BEGIN), 1)
        self.assertIn("<calibrationMatrix>0 -1 1 1 0 0</calibrationMatrix>", content)

    def test_prefers_display_config_from_wizard_context(self):
        host = FakeHost(touchscreen=True)
        context = WizardContext(host=host, ui=FakeUI())
        context.state["display_config"] = DisplayConfig(
            output="DSI-1",
            transform="270",
            choice_id="clockwise",
            applied_live=True,
        )

        report = TouchStep().apply(host, context=context)

        content = host.files["/home/pi/.config/labwc/rc.xml"]
        self.assertIn('<touch mapToOutput="DSI-1" />', content)
        self.assertIn("<calibrationMatrix>0 1 0 -1 0 1</calibrationMatrix>", content)
        self.assertIn("clockwise", report.lower())

    def test_records_fallback_display_config_in_wizard_context(self):
        host = FakeHost(touchscreen=True)
        RotationStep().apply(host, "counterclockwise")
        context = WizardContext(host=host, ui=FakeUI())

        TouchStep().apply(host, context=context)

        self.assertEqual(
            context.state["display_config"],
            DisplayConfig(
                output="HDMI-A-1",
                transform="90",
                choice_id="counterclockwise",
                applied_live=False,
            ),
        )


class UpsertTouchBlockTests(unittest.TestCase):
    def test_creates_minimal_rc_xml_when_missing(self):
        content = upsert_touch_block("", output="DSI-1", matrix="0 -1 1 1 0 0")

        self.assertIn("<labwc_config>", content)
        self.assertIn('<touch mapToOutput="DSI-1" />', content)

    def test_converts_openbox_root_to_labwc_root(self):
        content = upsert_touch_block(
            (
                '<?xml version="1.0"?>\n'
                '<openbox_config xmlns="http://openbox.org/3.4/rc">\n'
                "</openbox_config>\n"
            ),
            output="DSI-1",
            matrix="0 -1 1 1 0 0",
        )

        self.assertIn("<labwc_config", content)
        self.assertNotIn("<openbox_config", content)
        self.assertIn('<touch mapToOutput="DSI-1" />', content)


if __name__ == "__main__":
    unittest.main()


from pi_kiosk.host import WaylandOutput  # noqa: E402
from pi_kiosk.steps.touch import TOUCH_DISPLAY_PROMPT  # noqa: E402

TWO_OUTPUTS = [WaylandOutput("HDMI-A-1", "Samsung"), WaylandOutput("HDMI-A-2", "Dell")]


class MultiDisplayTouchTests(unittest.TestCase):
    def test_asks_which_display_has_the_touchscreen(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, touchscreen=True)
        ui = FakeUI(answers={TOUCH_DISPLAY_PROMPT: "HDMI-A-2"})

        answer = TouchStep().ask(ui, WizardContext(host=host, ui=ui))

        self.assertEqual(answer, "HDMI-A-2")

    def test_does_not_ask_without_a_touchscreen(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, touchscreen=False)
        ui = FakeUI()

        self.assertIsNone(TouchStep().ask(ui, WizardContext(host=host, ui=ui)))
        self.assertEqual(ui.prompts, [])

    def test_maps_touch_to_the_chosen_display_even_without_rotation(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, touchscreen=True)
        context = WizardContext(host=host, ui=FakeUI())
        context.state["display_configs"] = [
            DisplayConfig("HDMI-A-1", "270", "clockwise"),
            DisplayConfig("HDMI-A-2", "normal", "none"),
        ]

        report = TouchStep().apply(host, "HDMI-A-2", context)

        rc_xml = host.files["/home/pi/.config/labwc/rc.xml"]
        self.assertIn('<touch mapToOutput="HDMI-A-2" />', rc_xml)
        self.assertNotIn("calibrationMatrix", rc_xml)
        self.assertIn("HDMI-A-2", report)

    def test_uses_the_chosen_display_rotation_for_calibration(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS, touchscreen=True)
        context = WizardContext(host=host, ui=FakeUI())
        context.state["display_configs"] = [
            DisplayConfig("HDMI-A-1", "270", "clockwise"),
            DisplayConfig("HDMI-A-2", "normal", "none"),
        ]

        TouchStep().apply(host, "HDMI-A-1", context)

        rc_xml = host.files["/home/pi/.config/labwc/rc.xml"]
        self.assertIn('<touch mapToOutput="HDMI-A-1" />', rc_xml)
        self.assertIn("<calibrationMatrix>0 1 0 -1 0 1</calibrationMatrix>", rc_xml)

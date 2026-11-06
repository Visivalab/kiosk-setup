import io
import unittest

from tests.fake_ui import FakeUI
from tests.fakes import FakeHost

from pi_kiosk.app import Wizard
from pi_kiosk.cleanup import run_cleanup
from pi_kiosk.cli import main
from pi_kiosk.desktop_session import (
    ACCOUNTS_DIR,
    GDM_CONFIG,
    LABWC_PACKAGES,
    LABWC_SESSION_FILE,
    LIGHTDM_DROPIN,
    SLEEP_TARGETS,
    set_ini_values,
)
from pi_kiosk.display import parse_drm_connectors
from pi_kiosk.host import WaylandOutput, WebAppSource
from pi_kiosk.machine import LINUX_DESKTOP, RASPBERRY_PI, detect_platform, display_manager_from_unit
from pi_kiosk.steps.project_kiosk import TYPE_OF_PROJECT_PROMPT
from pi_kiosk.steps.register_totem import REGISTER_TOTEM_PROMPT
from pi_kiosk.steps.rustdesk import RUSTDESK_INSTALL_PROMPT
from pi_kiosk.steps.webapp_kiosk import WebAppKioskStep

UBUNTU = 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\nVERSION_ID="24.04"\n'
DEBIAN = 'ID=debian\nVERSION_ID="12"\n'
FEDORA = 'ID=fedora\n'
GDM_CUSTOM = (
    "# GDM configuration storage\n"
    "[daemon]\n"
    "# Uncomment the line below to force the login screen to use Xorg\n"
    "#WaylandEnable=false\n"
    "# Enabling automatic login\n"
    "#  AutomaticLoginEnable = true\n"
    "#  AutomaticLogin = user1\n"
    "\n"
    "[security]\n"
)
RELEASE = "demo-app/demo-app-dist.zip"
ANSWERS = {
    "Screen rotation": "none",
    RUSTDESK_INSTALL_PROMPT: "no",
    TYPE_OF_PROJECT_PROMPT: "webapp",
    "S3 zip - example: screen_1_de/screen_1_de-dist.zip": RELEASE,
    REGISTER_TOTEM_PROMPT: "no",
    "Choose what to do next.": "close",
}


def desktop_host(display_manager="gdm3", **kwargs) -> FakeHost:
    files = {LABWC_SESSION_FILE: "[Desktop Entry]\n"}
    if display_manager == "gdm3":
        files[GDM_CONFIG] = GDM_CUSTOM
    files.update(kwargs.pop("files", {}))
    return FakeHost(
        raspberry_pi=False,
        platform=LINUX_DESKTOP,
        display_manager=display_manager,
        files=files,
        **kwargs,
    )


class DetectPlatformTests(unittest.TestCase):
    def detect(self, **overrides):
        values = {
            "model": None,
            "has_rpi_issue": False,
            "os_release": UBUNTU,
            "proc_version": "Linux version 6.8.0-45-generic",
            "display_manager": "gdm3",
            "in_container": False,
        }
        values.update(overrides)
        return detect_platform(**values)

    def test_raspberry_pi_wins(self):
        self.assertEqual(self.detect(model="Raspberry Pi 5 Model B", os_release=DEBIAN), RASPBERRY_PI)

    def test_ubuntu_and_debian_desktops_are_supported(self):
        self.assertEqual(self.detect(), LINUX_DESKTOP)
        self.assertEqual(self.detect(os_release=DEBIAN, display_manager="lightdm"), LINUX_DESKTOP)

    def test_servers_wsl_containers_and_other_distros_are_refused(self):
        self.assertIsNone(self.detect(display_manager=None))
        self.assertIsNone(self.detect(proc_version="Linux version 6.6.87.2-microsoft-standard-WSL2"))
        self.assertIsNone(self.detect(in_container=True))
        self.assertIsNone(self.detect(os_release=FEDORA))

    def test_display_manager_comes_from_the_systemd_unit(self):
        self.assertEqual(display_manager_from_unit("/lib/systemd/system/gdm3.service"), "gdm3")
        self.assertEqual(display_manager_from_unit("/usr/lib/systemd/system/gdm.service"), "gdm3")
        self.assertEqual(display_manager_from_unit("/lib/systemd/system/lightdm.service"), "lightdm")
        self.assertIsNone(display_manager_from_unit("/lib/systemd/system/sddm.service"))
        self.assertIsNone(display_manager_from_unit(None))


class ContainerDetectionTests(unittest.TestCase):
    def test_systemd_container_marker_counts_as_a_container(self):
        from pi_kiosk.linux import _in_container

        self.assertTrue(_in_container(lambda path: path == "/run/systemd/container"))
        self.assertTrue(_in_container(lambda path: path == "/.dockerenv"))
        self.assertFalse(_in_container(lambda path: False))


class DrmConnectorTests(unittest.TestCase):
    def test_lists_connected_outputs_with_their_wayland_names(self):
        edid = bytearray(128)
        edid[54 + 3] = 0xFC
        edid[54 + 5 : 54 + 18] = b"DELL P2419H\n "
        self.assertEqual(
            parse_drm_connectors(
                [
                    {"dir": "card1-HDMI-A-2", "status": "connected", "modes": "1920x1080\n1280x720\n", "edid": bytes(edid)},
                    {"dir": "card1-HDMI-A-1", "status": "connected", "modes": "3840x2160\n", "edid": b""},
                    {"dir": "card1-DP-1", "status": "disconnected", "modes": "", "edid": b""},
                ]
            ),
            [
                WaylandOutput("HDMI-A-1", "", 3840, 2160),
                WaylandOutput("HDMI-A-2", "DELL P2419H", 1920, 1080),
            ],
        )


class IniTests(unittest.TestCase):
    def test_sets_keys_inside_the_section_and_keeps_comments(self):
        updated = set_ini_values(GDM_CUSTOM, "daemon", {"AutomaticLoginEnable": "True", "AutomaticLogin": "kiosk"})
        self.assertIn("[daemon]\nAutomaticLoginEnable=True\nAutomaticLogin=kiosk\n", updated)
        self.assertIn("#  AutomaticLogin = user1", updated)
        self.assertLess(updated.index("AutomaticLogin=kiosk"), updated.index("[security]"))

    def test_replaces_and_removes_existing_keys(self):
        text = "[User]\nSession=ubuntu\nSystemAccount=false\n"
        self.assertEqual(
            set_ini_values(text, "User", {"Session": "labwc"}),
            "[User]\nSession=labwc\nSystemAccount=false\n",
        )
        self.assertEqual(set_ini_values(text, "User", {"Session": None}), "[User]\nSystemAccount=false\n")

    def test_adds_a_missing_section(self):
        self.assertEqual(set_ini_values("", "User", {"Session": "labwc"}), "[User]\nSession=labwc\n")


class DesktopWizardTests(unittest.TestCase):
    def test_gdm_desktop_gets_labwc_autologin_without_raspi_config(self):
        host = desktop_host()

        Wizard(host, FakeUI(answers=dict(ANSWERS))).run()

        self.assertFalse(any(command[0] == "raspi-config" for command in host.commands))
        self.assertIn(["apt-get", "update"], host.commands)
        self.assertIn(["apt-get", "install", "-y", *LABWC_PACKAGES], host.commands)
        self.assertIn(["systemctl", "mask", *SLEEP_TARGETS], host.commands)
        gdm = host.files[GDM_CONFIG]
        self.assertIn("AutomaticLoginEnable=True\nAutomaticLogin=pi\n", gdm)
        self.assertIn("Session=labwc", host.files[f"{ACCOUNTS_DIR}/pi"])
        self.assertIn("SessionType=wayland", host.files[f"{ACCOUNTS_DIR}/pi"])
        self.assertIn("wlopm --on", host.files["/home/pi/.config/labwc/autostart"])

    def test_lightdm_desktop_gets_a_drop_in(self):
        host = desktop_host(display_manager="lightdm")

        Wizard(host, FakeUI(answers=dict(ANSWERS))).run()

        self.assertEqual(
            host.files[LIGHTDM_DROPIN],
            "[Seat:*]\nautologin-user=pi\nautologin-session=labwc\nuser-session=labwc\n",
        )

    def test_warns_when_gdm_has_wayland_disabled(self):
        host = desktop_host(files={GDM_CONFIG: "[daemon]\nWaylandEnable=false\n"})
        ui = FakeUI(answers=dict(ANSWERS))

        Wizard(host, ui).run()

        self.assertTrue(any("WaylandEnable=false" in message for message in ui.messages))

    def test_fails_clearly_when_labwc_is_not_installable(self):
        host = desktop_host()
        del host.files[LABWC_SESSION_FILE]

        with self.assertRaisesRegex(Exception, "labwc"):
            Wizard(host, FakeUI(answers=dict(ANSWERS))).run()

    def test_webapp_installs_chromium_on_a_desktop_when_missing(self):
        host = desktop_host(chromium=None)
        host.browser = "chromium-browser"

        WebAppKioskStep().apply(host, WebAppSource(release_url="https://example.test/a.zip"))

        self.assertIn(("chromium-browser",), host.installed_packages)


    def test_a_saved_xorg_session_type_is_replaced_by_wayland(self):
        host = desktop_host(files={f"{ACCOUNTS_DIR}/pi": "[User]\nSession=ubuntu-xorg\nSessionType=x11\n"})

        Wizard(host, FakeUI(answers=dict(ANSWERS))).run()

        accounts = host.files[f"{ACCOUNTS_DIR}/pi"]
        self.assertIn("Session=labwc\nSessionType=wayland\n", accounts)
        self.assertNotIn("x11", accounts)

    def test_final_action_without_a_desktop_session_is_a_warning_not_a_failure(self):
        from pi_kiosk.linux import DesktopSessionUnavailable

        host = desktop_host()

        def no_session(launcher):
            raise DesktopSessionUnavailable("No desktop Wayland session detected.")

        host.launch_webapp_server_now = no_session
        answers = dict(ANSWERS)
        reports = Wizard(host, FakeUI(answers=answers)).run()

        self.assertIn("next graphical login", reports[-1])
        self.assertTrue(reports[-1].startswith("Done:"))


class DesktopCleanupTests(unittest.TestCase):
    def test_gdm_cleanup_turns_autologin_off_and_restores_the_default_session(self):
        host = desktop_host()
        Wizard(host, FakeUI(answers=dict(ANSWERS))).run()

        run_cleanup(host)

        self.assertIn("AutomaticLoginEnable=False", host.files[GDM_CONFIG])
        self.assertNotIn("Session=labwc", host.files[f"{ACCOUNTS_DIR}/pi"])
        self.assertNotIn("SessionType=wayland", host.files[f"{ACCOUNTS_DIR}/pi"])
        self.assertIn(["systemctl", "unmask", *SLEEP_TARGETS], host.commands)
        self.assertFalse(any(command[0] == "raspi-config" for command in host.commands))

    def test_lightdm_cleanup_removes_the_drop_in(self):
        host = desktop_host(display_manager="lightdm")
        Wizard(host, FakeUI(answers=dict(ANSWERS))).run()

        run_cleanup(host)

        self.assertNotIn(LIGHTDM_DROPIN, host.files)


class UnsupportedMachineTests(unittest.TestCase):
    def test_cli_explains_what_is_supported(self):
        stderr = io.StringIO()

        code = main(host=FakeHost(raspberry_pi=False), ui=FakeUI(), stderr=stderr)

        self.assertEqual(code, 2)
        self.assertIn("Raspberry Pi", stderr.getvalue())
        self.assertIn("Ubuntu", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from tests.fakes import FakeHost
from tests.test_gui_model import TWO_OUTPUTS, single_form

from pi_kiosk.gui_launcher import frontend_environment
from pi_kiosk.gui_session import GuiSession
from pi_kiosk.kiosk_state import KIOSK_STATE_PATH


class GuiSessionTests(unittest.TestCase):
    def setUp(self):
        self.events = []

    def session(self, host):
        return GuiSession(host, self.events.append)

    def last_done(self):
        return [event for event in self.events if event["type"] == "done"][-1]

    def logs(self):
        return [event["text"] for event in self.events if event["type"] == "log"]

    def test_configure_streams_progress_and_reports_success(self):
        host = FakeHost()

        self.session(host).handle({"type": "configure", "form": single_form()})

        self.assertEqual(self.last_done(), {"type": "done", "request": "configure", "ok": True, "message": "Kiosk setup finished."})
        self.assertTrue(any(text.startswith("Done: screen rotation") for text in self.logs()))
        self.assertTrue(any(text.startswith("[....] Downloading webapp ZIP") for text in self.logs()))
        self.assertIn(KIOSK_STATE_PATH, host.files)

    def test_invalid_form_changes_nothing(self):
        host = FakeHost()

        self.session(host).handle({"type": "configure", "form": single_form(rustdeskPasswordConfirm="no")})

        done = self.last_done()
        self.assertFalse(done["ok"])
        self.assertIn("do not match", done["message"])
        self.assertEqual(host.commands, [])
        self.assertEqual(host.files, {})

    def test_register_only_uses_the_saved_setup(self):
        host = FakeHost(wayland_outputs=TWO_OUTPUTS)
        host.files[KIOSK_STATE_PATH] = json.dumps(
            {
                "version": 1,
                "projectType": "video",
                "skipRustDesk": False,
                "displays": [
                    {"number": 1, "output": "HDMI-A-1", "type": "video", "rotation": "none", "source": "a", "audio": True},
                    {"number": 2, "output": "HDMI-A-2", "type": "video", "rotation": "none", "source": "b", "audio": False},
                ],
            }
        )

        self.session(host).handle(
            {"type": "register", "form": single_form(totemName="Lobby", totemType="webapp")}
        )

        self.assertTrue(self.last_done()["ok"])
        request = host.totem_registration_requests[0]
        self.assertEqual(request["totem_type"], "video")
        self.assertEqual(len(request["screens"]), 2)
        self.assertEqual(host.commands, [])

    def test_register_only_sets_up_rustdesk_when_it_is_not_configured(self):
        host = FakeHost(rustdesk_present=False)

        self.session(host).handle(
            {"type": "register", "form": single_form(totemName="Lobby", totemType="webapp")}
        )

        self.assertTrue(self.last_done()["ok"])
        self.assertEqual(host.rustdesk_passwords, ["secret"])
        self.assertEqual(host.totem_registration_requests[0]["connection"].rustdesk_password, "secret")

    def test_register_only_sets_the_password_when_rustdesk_has_none(self):
        host = FakeHost(rustdesk_present=True, saved_rustdesk_password=None)

        self.session(host).handle(
            {"type": "register", "form": single_form(totemName="Lobby", totemType="webapp")}
        )

        self.assertEqual(host.rustdesk_passwords, [])
        self.assertEqual(host.configured_rustdesk_passwords, ["secret"])

    def test_register_only_refuses_when_rustdesk_is_unconfigured_and_no_password_given(self):
        host = FakeHost(rustdesk_present=False)

        self.session(host).handle(
            {
                "type": "register",
                "form": single_form(
                    totemName="Lobby", totemType="webapp", rustdeskPassword="", rustdeskPasswordConfirm=""
                ),
            }
        )

        done = self.last_done()
        self.assertFalse(done["ok"])
        self.assertIn("Skip RustDesk", done["message"])
        self.assertEqual(host.totem_registration_requests, [])

    def test_register_only_keeps_an_existing_rustdesk_setup(self):
        host = FakeHost(rustdesk_present=True, saved_rustdesk_password="already")

        self.session(host).handle(
            {"type": "register", "form": single_form(totemName="Lobby", totemType="webapp", rustdeskPassword="")}
        )

        self.assertTrue(self.last_done()["ok"])
        self.assertEqual(host.rustdesk_passwords, [])
        self.assertEqual(host.configured_rustdesk_passwords, [])
        self.assertEqual(host.totem_registration_requests[0]["connection"].rustdesk_password, "already")

    def test_register_only_needs_a_name(self):
        self.session(FakeHost()).handle({"type": "register", "form": single_form(totemName="")})

        self.assertFalse(self.last_done()["ok"])

    def test_cleanup_reports_each_step(self):
        host = FakeHost()

        self.session(host).handle({"type": "cleanup"})

        self.assertTrue(self.last_done()["ok"])
        self.assertTrue(any("cleanup completed" in text for text in self.logs()))

    def test_unexpected_errors_are_reported_not_raised(self):
        host = FakeHost()

        def broken(*args, **kwargs):
            raise RuntimeError("boom")

        host.deploy_webapp = broken
        self.session(host).handle({"type": "configure", "form": single_form()})

        done = self.last_done()
        self.assertFalse(done["ok"])
        self.assertIn("boom", done["message"])


class FrontendEnvironmentTests(unittest.TestCase):
    def test_uses_the_desktop_display_and_session(self):
        env = frontend_environment(
            {"DISPLAY": ":0", "XAUTHORITY": "/home/pi/.Xauthority", "PATH": "/usr/bin"},
            {"XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-0", "HOME": "/home/pi"},
            x11_socket=False,
        )
        self.assertEqual(
            env,
            {
                "XDG_RUNTIME_DIR": "/run/user/1000",
                "WAYLAND_DISPLAY": "wayland-0",
                "HOME": "/home/pi",
                "DISPLAY": ":0",
                "XAUTHORITY": "/home/pi/.Xauthority",
            },
        )

    def test_falls_back_to_the_xwayland_socket(self):
        env = frontend_environment({}, {"XDG_RUNTIME_DIR": "/run/user/1000"}, x11_socket=True)
        self.assertEqual(env["DISPLAY"], ":0")

    def test_no_display_means_no_window(self):
        self.assertIsNone(frontend_environment({}, None, x11_socket=False))


if __name__ == "__main__":
    unittest.main()

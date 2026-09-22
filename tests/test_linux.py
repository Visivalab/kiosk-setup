import json
import stat
import subprocess
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock
from urllib import error

from pi_kiosk.errors import UserFacingError
from pi_kiosk.host import TotemConnectionDetails, TotemStatusReporterConfig, VideoSource, WebAppSource
from pi_kiosk.linux import (
    LinuxHost,
    NeedSudoUser,
    _libinput_reports_touch,
    _select_rustdesk_deb_asset,
)


class FakeResponse(BytesIO):
    def __init__(
        self,
        payload: bytes,
        headers: dict[str, str] | None = None,
        status: int = 200,
    ) -> None:
        super().__init__(payload)
        self.headers = headers or {}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self) -> int:
        return self.status


class LinuxHostTests(unittest.TestCase):
    def test_root_shell_without_sudo_user_is_rejected(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("os.geteuid", return_value=0):
                with self.assertRaises(NeedSudoUser):
                    LinuxHost().user()

    def test_mkdir_owns_each_directory_under_the_desktop_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home" / "pi"
            target = home / ".config" / "labwc"
            owned: list[Path] = []
            host = LinuxHost()

            with mock.patch.object(host, "home", return_value=str(home)):
                with mock.patch.object(host, "_own", side_effect=owned.append):
                    host.mkdir(str(target))

            self.assertTrue(target.is_dir())
            self.assertEqual(
                owned,
                [
                    target,
                    target.parent,
                    home,
                ],
            )

    def test_libinput_touch_detection_reports_true_for_touch_capability(self):
        self.assertTrue(
            _libinput_reports_touch(
                "Device: Foo\nCapabilities: keyboard pointer touch\n"
            )
        )

    def test_libinput_touch_detection_reports_false_without_touch_capability(self):
        self.assertFalse(
            _libinput_reports_touch(
                "Device: Foo\nCapabilities: keyboard pointer\n"
            )
        )

    def test_selects_arm64_rustdesk_deb_asset(self):
        asset = _select_rustdesk_deb_asset(
            {
                "assets": [
                    {"name": "rustdesk-1.4.3-x86_64.deb", "browser_download_url": "x"},
                    {"name": "rustdesk-1.4.3-aarch64.deb", "browser_download_url": "a"},
                ]
            },
            "arm64",
        )
        self.assertEqual(asset["name"], "rustdesk-1.4.3-aarch64.deb")

    def test_rejects_unsupported_rustdesk_architecture(self):
        with self.assertRaises(UserFacingError):
            _select_rustdesk_deb_asset({"assets": []}, "mips")

    def test_install_rustdesk_persists_password_for_later_registration(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            saved_password_path = Path(tmp) / "etc" / "pi-kiosk" / "rustdesk.json"

            with mock.patch.object(
                host,
                "_read_json",
                return_value={
                    "assets": [
                        {
                            "name": "rustdesk-1.4.3-aarch64.deb",
                            "browser_download_url": "https://example.com/rustdesk.deb",
                        }
                    ]
                },
            ):
                with mock.patch.object(host, "_debian_architecture", return_value="arm64"):
                    with mock.patch.object(host, "_download_file"):
                        with mock.patch.object(host, "_restart_rustdesk_service"):
                            with mock.patch.object(host, "_rustdesk_get_id", return_value="987 654 321"):
                                with mock.patch("pi_kiosk.linux.RUSTDESK_CREDENTIALS_PATH", saved_password_path):
                                    with mock.patch(
                                        "subprocess.run",
                                        side_effect=[
                                            subprocess.CompletedProcess(
                                                args=[],
                                                returncode=0,
                                                stdout="",
                                                stderr="",
                                            ),
                                            subprocess.CompletedProcess(
                                                args=[],
                                                returncode=0,
                                                stdout="",
                                                stderr="",
                                            ),
                                            subprocess.CompletedProcess(
                                                args=[],
                                                returncode=0,
                                                stdout="password\n",
                                                stderr="",
                                            ),
                                            subprocess.CompletedProcess(
                                                args=[],
                                                returncode=0,
                                                stdout="",
                                                stderr="",
                                            ),
                                            subprocess.CompletedProcess(
                                                args=[],
                                                returncode=0,
                                                stdout="use-permanent-password\n",
                                                stderr="",
                                            ),
                                            subprocess.CompletedProcess(
                                                args=[],
                                                returncode=0,
                                                stdout="Done!\n",
                                                stderr="",
                                            ),
                                        ],
                                    ) as run:
                                        host.install_rustdesk("secret-pass")

            self.assertEqual(
                json.loads(saved_password_path.read_text(encoding="utf-8")),
                {"password": "secret-pass"},
            )
            self.assertEqual(saved_password_path.stat().st_mode & 0o777, 0o600)
            run.assert_any_call(
                ["rustdesk", "--option", "approve-mode", "password"],
                check=True,
                text=True,
                capture_output=True,
            )
            run.assert_any_call(
                ["rustdesk", "--option", "approve-mode"],
                check=True,
                text=True,
                capture_output=True,
            )
            run.assert_any_call(
                ["rustdesk", "--option", "verification-method", "use-permanent-password"],
                check=True,
                text=True,
                capture_output=True,
            )
            run.assert_any_call(
                ["rustdesk", "--option", "verification-method"],
                check=True,
                text=True,
                capture_output=True,
            )
            run.assert_any_call(
                ["rustdesk", "--password", "secret-pass"],
                check=True,
                text=True,
                capture_output=True,
            )

    def test_rustdesk_installed_checks_path(self):
        host = LinuxHost()
        with mock.patch("shutil.which", return_value="/usr/bin/rustdesk"):
            self.assertTrue(host.rustdesk_installed())
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(host.rustdesk_installed())

    def test_webapp_deployment_disables_context_menu_and_text_selection(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home" / "pi"
            archive = root / "webapp.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("index.html", "<html><head></head><body>App</body></html>")

            def download(_url, destination, **_kwargs):
                destination.write_bytes(archive.read_bytes())

            with mock.patch.object(host, "home", return_value=str(home)):
                with mock.patch.object(host, "_download_file", side_effect=download):
                    with mock.patch.object(host, "_own_within_home"):
                        with mock.patch.object(host, "_own_tree"):
                            deployment = host.deploy_webapp(WebAppSource("https://example/app.zip"))

            html = Path(deployment.app_dir, "index.html").read_text(encoding="utf-8")

        self.assertIn("user-select: none", html)
        self.assertIn('addEventListener("contextmenu"', html)
        self.assertIn("preventDefault()", html)

    def test_resolve_webapp_root_uses_single_wrapping_directory(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            extracted_root = Path(tmp) / "webapp"
            app_root = extracted_root / "screen_1_de-dist"
            app_root.mkdir(parents=True)
            (app_root / "index.html").write_text("<html></html>", encoding="utf-8")

            resolved = host._resolve_webapp_root(extracted_root)

        self.assertEqual(resolved, app_root)

    def test_resolve_webapp_root_rejects_missing_index_html(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            extracted_root = Path(tmp) / "webapp"
            extracted_root.mkdir(parents=True)
            (extracted_root / "assets").mkdir()
            (extracted_root / "app.js").write_text("console.log('hi')", encoding="utf-8")

            with self.assertRaises(UserFacingError):
                host._resolve_webapp_root(extracted_root)

    def test_extract_webapp_zip_happy_path_preserves_files(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "webapp.zip"
            extracted_root = Path(tmp) / "out"
            extracted_root.mkdir()
            with zipfile.ZipFile(archive_path, "w") as bundle:
                bundle.writestr("screen_1_de-dist/index.html", "<html></html>")
                bundle.writestr("screen_1_de-dist/assets/app.js", "console.log('hi')")

            host._extract_webapp_zip(archive_path, extracted_root)

            self.assertEqual(
                (extracted_root / "screen_1_de-dist" / "index.html").read_text(encoding="utf-8"),
                "<html></html>",
            )
            self.assertEqual(
                (extracted_root / "screen_1_de-dist" / "assets" / "app.js").read_text(
                    encoding="utf-8"
                ),
                "console.log('hi')",
            )

    def test_extract_webapp_zip_rejects_absolute_paths(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "webapp.zip"
            extracted_root = Path(tmp) / "out"
            extracted_root.mkdir()
            with zipfile.ZipFile(archive_path, "w") as bundle:
                bundle.writestr("/etc/passwd", "nope")

            with self.assertRaises(UserFacingError):
                host._extract_webapp_zip(archive_path, extracted_root)

    def test_extract_webapp_zip_rejects_parent_traversal_paths(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "webapp.zip"
            extracted_root = Path(tmp) / "out"
            extracted_root.mkdir()
            with zipfile.ZipFile(archive_path, "w") as bundle:
                bundle.writestr("../escape.txt", "nope")

            with self.assertRaises(UserFacingError):
                host._extract_webapp_zip(archive_path, extracted_root)

    def test_extract_webapp_zip_rejects_symbolic_links(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "webapp.zip"
            extracted_root = Path(tmp) / "out"
            extracted_root.mkdir()
            link = zipfile.ZipInfo("current")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive_path, "w") as bundle:
                bundle.writestr(link, "screen_1_de-dist")

            with self.assertRaises(UserFacingError):
                host._extract_webapp_zip(archive_path, extracted_root)

    def test_extract_webapp_zip_wraps_oserror_as_user_facing_error(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "webapp.zip"
            extracted_root = Path(tmp) / "out"
            extracted_root.mkdir()
            with zipfile.ZipFile(archive_path, "w") as bundle:
                bundle.writestr("index.html", "<html></html>")

            with mock.patch("pi_kiosk.linux.shutil.copyfileobj", side_effect=OSError("disk full")):
                with self.assertRaises(UserFacingError):
                    host._extract_webapp_zip(archive_path, extracted_root)

    def test_extract_webapp_zip_wraps_runtimeerror_as_user_facing_error(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "webapp.zip"
            extracted_root = Path(tmp) / "out"
            extracted_root.mkdir()
            with zipfile.ZipFile(archive_path, "w") as bundle:
                bundle.writestr("index.html", "<html></html>")

            with mock.patch(
                "pi_kiosk.linux.shutil.copyfileobj", side_effect=RuntimeError("zip stream failed")
            ):
                with self.assertRaises(UserFacingError):
                    host._extract_webapp_zip(archive_path, extracted_root)

    def test_read_json_wraps_network_errors_with_generic_github_message(self):
        host = LinuxHost()
        with mock.patch("urllib.request.urlopen", side_effect=error.URLError("offline")):
            with self.assertRaisesRegex(UserFacingError, "Could not reach GitHub: offline."):
                host._read_json("https://api.github.com/repos/rustdesk/rustdesk/releases/latest")

    def test_configure_rustdesk_password_persists_without_reinstalling(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            saved_password_path = Path(tmp) / "etc" / "pi-kiosk" / "rustdesk.json"

            with mock.patch("pi_kiosk.linux.RUSTDESK_CREDENTIALS_PATH", saved_password_path):
                with mock.patch.object(host, "_restart_rustdesk_service") as restart:
                    with mock.patch(
                        "subprocess.run",
                        side_effect=[
                            subprocess.CompletedProcess(
                                args=[],
                                returncode=0,
                                stdout="",
                                stderr="",
                            ),
                            subprocess.CompletedProcess(
                                args=[],
                                returncode=0,
                                stdout="password\n",
                                stderr="",
                            ),
                            subprocess.CompletedProcess(
                                args=[],
                                returncode=0,
                                stdout="",
                                stderr="",
                            ),
                            subprocess.CompletedProcess(
                                args=[],
                                returncode=0,
                                stdout="use-permanent-password\n",
                                stderr="",
                            ),
                            subprocess.CompletedProcess(
                                args=[],
                                returncode=0,
                                stdout="Done!\n",
                                stderr="",
                            ),
                        ],
                    ) as run:
                        host.configure_rustdesk_password("secret-pass")

            self.assertEqual(
                json.loads(saved_password_path.read_text(encoding="utf-8")),
                {"password": "secret-pass"},
            )
            self.assertEqual(saved_password_path.stat().st_mode & 0o777, 0o600)
            run.assert_any_call(
                ["rustdesk", "--option", "approve-mode", "password"],
                check=True,
                text=True,
                capture_output=True,
            )
            run.assert_any_call(
                ["rustdesk", "--option", "approve-mode"],
                check=True,
                text=True,
                capture_output=True,
            )
            run.assert_any_call(
                ["rustdesk", "--option", "verification-method", "use-permanent-password"],
                check=True,
                text=True,
                capture_output=True,
            )
            run.assert_any_call(
                ["rustdesk", "--option", "verification-method"],
                check=True,
                text=True,
                capture_output=True,
            )
            run.assert_any_call(
                ["rustdesk", "--password", "secret-pass"],
                check=True,
                text=True,
                capture_output=True,
            )
            restart.assert_called_once_with()

    def test_configure_rustdesk_password_starts_user_server_when_cli_does_not_confirm(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            saved_password_path = Path(tmp) / "etc" / "pi-kiosk" / "rustdesk.json"

            with mock.patch("pi_kiosk.linux.RUSTDESK_CREDENTIALS_PATH", saved_password_path):
                with mock.patch.object(host, "_restart_rustdesk_service") as restart:
                    with mock.patch.object(
                        host,
                        "run_in_desktop_session",
                        return_value=subprocess.CompletedProcess(
                            args=[],
                            returncode=0,
                            stdout="",
                            stderr="",
                        ),
                    ) as start:
                        with mock.patch("pi_kiosk.linux.time.sleep") as sleep:
                            with mock.patch(
                                "subprocess.run",
                                side_effect=[
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="Failed to connect to the RustDesk main service\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="password\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="use-permanent-password\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="Done!\n",
                                        stderr="",
                                    ),
                                ],
                            ):
                                host.configure_rustdesk_password("secret-pass")

            self.assertEqual(
                json.loads(saved_password_path.read_text(encoding="utf-8")),
                {"password": "secret-pass"},
            )
            start.assert_called_once_with(
                [
                    "sh",
                    "-lc",
                    "nohup rustdesk --server >/dev/null 2>&1 </dev/null &",
                ],
                check=False,
            )
            sleep.assert_called_once_with(1)
            restart.assert_called_once_with()

    def test_configure_rustdesk_password_raises_when_rustdesk_never_confirms(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            saved_password_path = Path(tmp) / "etc" / "pi-kiosk" / "rustdesk.json"

            with mock.patch("pi_kiosk.linux.RUSTDESK_CREDENTIALS_PATH", saved_password_path):
                with mock.patch.object(host, "_restart_rustdesk_service") as restart:
                    with mock.patch.object(
                        host,
                        "run_in_desktop_session",
                        return_value=subprocess.CompletedProcess(
                            args=[],
                            returncode=0,
                            stdout="",
                            stderr="",
                        ),
                    ) as start:
                        with mock.patch("pi_kiosk.linux.time.sleep") as sleep:
                            with mock.patch(
                                "subprocess.run",
                                side_effect=[
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="Failed to connect to the RustDesk main service\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="\n",
                                        stderr="",
                                    ),
                                    subprocess.CompletedProcess(
                                        args=[],
                                        returncode=0,
                                        stdout="Failed to connect to the RustDesk main service\n",
                                        stderr="",
                                    ),
                                ],
                            ):
                                with self.assertRaisesRegex(
                                    UserFacingError,
                                    "did not confirm the unattended-access configuration.*"
                                    "approve-mode=empty.*"
                                    "Failed to connect to the RustDesk main service.*"
                                    "Open RustDesk once",
                                ):
                                    host.configure_rustdesk_password("secret-pass")

            self.assertFalse(saved_password_path.exists())
            start.assert_called_once_with(
                [
                    "sh",
                    "-lc",
                    "nohup rustdesk --server >/dev/null 2>&1 </dev/null &",
                ],
                check=False,
            )
            sleep.assert_called_once_with(1)
            restart.assert_not_called()

    def test_run_in_desktop_session_passes_home_and_dbus_env_to_sudo(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "run" / "user" / "1000"
            runtime_dir.mkdir(parents=True)
            (runtime_dir / "wayland-1").touch()
            (runtime_dir / "bus").touch()
            user_info = mock.Mock(pw_uid=1000, pw_dir="/home/pi")

            with mock.patch.object(host, "is_root", return_value=True):
                with mock.patch.object(host, "user", return_value="pi"):
                    with mock.patch("pwd.getpwnam", return_value=user_info):
                        with mock.patch.dict(
                            "os.environ",
                            {
                                "XDG_RUNTIME_DIR": str(runtime_dir),
                                "TERM": "xterm-256color",
                            },
                            clear=True,
                        ):
                            with mock.patch("subprocess.run") as run:
                                host.run_in_desktop_session(["rustdesk", "--server"])

        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["sudo", "-H", "-u", "pi"])
        self.assertIn(f"XDG_RUNTIME_DIR={runtime_dir}", command)
        self.assertIn("WAYLAND_DISPLAY=wayland-1", command)
        self.assertIn("HOME=/home/pi", command)
        self.assertIn(f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir / 'bus'}", command)
        self.assertIn("TERM=xterm-256color", command)

    def test_connection_details_uses_saved_rustdesk_password_when_not_provided(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            saved_password_path = Path(tmp) / "etc" / "pi-kiosk" / "rustdesk.json"
            saved_password_path.parent.mkdir(parents=True, exist_ok=True)
            saved_password_path.write_text('{"password": "secret-pass"}', encoding="utf-8")

            with mock.patch("pi_kiosk.linux.RUSTDESK_CREDENTIALS_PATH", saved_password_path):
                with mock.patch("pi_kiosk.linux._rustdesk_id", return_value="987 654 321"):
                    connection = host.connection_details()

        self.assertEqual(
            connection,
            TotemConnectionDetails(
                rustdesk_id="987 654 321",
                rustdesk_password="secret-pass",
            ),
        )

    def test_installs_missing_cursor_packages_with_apt(self):
        host = LinuxHost()

        with mock.patch("shutil.which", side_effect=["/usr/bin/wtype", "/usr/bin/swayidle"]):
            with mock.patch("subprocess.run") as run:
                host.ensure_packages_installed(("wtype", "swayidle"))

        run.assert_called_once_with(
            ["apt-get", "install", "-y", "wtype", "swayidle"],
            check=True,
            text=True,
        )

    def test_launch_kiosk_now_reconfigures_before_background_launch(self):
        host = LinuxHost()

        with mock.patch.object(host, "run_in_desktop_session") as run:
            host.launch_kiosk_now("/home/pi/.config/pi-kiosk/webapp-kiosk.sh")

        run.assert_called_once_with(
            [
                "sh",
                "-lc",
                "labwc --reconfigure >/dev/null 2>&1 || true; sleep 1; nohup bash /home/pi/.config/pi-kiosk/webapp-kiosk.sh >/dev/null 2>&1 </dev/null &",
            ],
            check=True,
        )

    def test_launch_webapp_server_now_starts_server_only_mode(self):
        host = LinuxHost()

        with mock.patch.object(host, "run_in_desktop_session") as run:
            host.launch_webapp_server_now("/home/pi/.config/pi-kiosk/webapp-kiosk.sh")

        run.assert_called_once_with(
            [
                "sh",
                "-lc",
                "nohup bash /home/pi/.config/pi-kiosk/webapp-kiosk.sh server-only >/dev/null 2>&1 </dev/null &",
            ],
            check=True,
        )

    def test_download_file_reports_percentage_progress_when_size_is_known(self):
        host = LinuxHost()
        progress: list[str] = []

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "demo.mp4"

            with mock.patch(
                "urllib.request.urlopen",
                return_value=FakeResponse(
                    b"x" * 16,
                    headers={"Content-Length": "16"},
                ),
            ):
                host._download_file(
                    "https://example.com/demo.mp4",
                    target,
                    description="video file",
                    progress=progress.append,
                )

            self.assertEqual(target.read_bytes(), b"x" * 16)

        self.assertEqual(
            progress,
            [
                "Downloading video file (0%)",
                "Downloading video file (100%)",
            ],
        )

    def test_deploy_video_rejects_html_content(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home" / "pi"
            home.mkdir(parents=True)

            with mock.patch.object(host, "home", return_value=str(home)):
                with mock.patch.object(host, "_own_within_home"):
                    with mock.patch.object(host, "_own_tree"):
                        with mock.patch(
                            "urllib.request.urlopen",
                            return_value=FakeResponse(
                                b"<html>login</html>",
                                headers={"Content-Type": "text/html"},
                            ),
                        ):
                            with self.assertRaisesRegex(UserFacingError, "video file"):
                                host.deploy_video(
                                    VideoSource(
                                        shared_url="https://www.dropbox.com/s/example/demo.mp4",
                                        download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
                                    )
                                )

    def test_deploy_video_uses_content_disposition_filename(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home" / "pi"
            home.mkdir(parents=True)

            with mock.patch.object(host, "home", return_value=str(home)):
                with mock.patch.object(host, "_own_within_home"):
                    with mock.patch.object(host, "_own_tree"):
                        with mock.patch(
                            "urllib.request.urlopen",
                            return_value=FakeResponse(
                                b"x" * 8,
                                headers={
                                    "Content-Type": "video/mp4",
                                    "Content-Length": "8",
                                    "Content-Disposition": 'attachment; filename="real-name.mp4"',
                                },
                            ),
                        ):
                            deployment = host.deploy_video(
                                VideoSource(
                                    shared_url="https://www.dropbox.com/s/example/demo.mp4",
                                    download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
                                )
                            )

            self.assertEqual(deployment.file_name, "real-name.mp4")
            self.assertEqual(
                deployment.video_path,
                str(home / ".local" / "share" / "pi-kiosk" / "video" / "current" / "real-name.mp4"),
            )

    def test_deploy_video_rejects_truncated_downloads(self):
        host = LinuxHost()

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home" / "pi"
            home.mkdir(parents=True)

            with mock.patch.object(host, "home", return_value=str(home)):
                with mock.patch.object(host, "_own_within_home"):
                    with mock.patch.object(host, "_own_tree"):
                        with mock.patch(
                            "urllib.request.urlopen",
                            return_value=FakeResponse(
                                b"short",
                                headers={
                                    "Content-Type": "video/mp4",
                                    "Content-Length": "10",
                                },
                            ),
                        ):
                            with self.assertRaisesRegex(UserFacingError, "incomplete"):
                                host.deploy_video(
                                    VideoSource(
                                        shared_url="https://www.dropbox.com/s/example/demo.mp4",
                                        download_url="https://www.dropbox.com/s/example/demo.mp4?dl=1",
                                    )
                                )

    def test_register_totem_posts_json_payload_with_machine_name(self):
        host = LinuxHost()

        with mock.patch("socket.gethostname", return_value="minipc-07"):
            with mock.patch("pi_kiosk.linux._machine_id", return_value="machine-123"):
                with mock.patch(
                    "urllib.request.urlopen",
                    return_value=FakeResponse(b"{}", status=201),
                ) as urlopen:
                    host.register_totem(
                        "https://dashboard.example.com/register-new-totem",
                        "totem-secret",
                        "minipc-07",
                        "webapp",
                        "Hall Screen",
                        "Main entrance display",
                        "Reception",
                        TotemConnectionDetails(
                            rustdesk_id="987 654 321",
                            rustdesk_password="secret-pass",
                        ),
                    )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://dashboard.example.com/register-new-totem")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer totem-secret")
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "totem_id": "minipc-07",
                "totemType": "webapp",
                "machineName": "minipc-07",
                "machineId": "machine-123",
                "name": "Hall Screen",
                "description": "Main entrance display",
                "location": "Reception",
                "rustdeskId": "987 654 321",
                "rustdeskPassword": "secret-pass",
                "registeredAt": mock.ANY,
            },
        )

    def test_register_totem_surfaces_backend_error_message(self):
        host = LinuxHost()
        http_error = error.HTTPError(
            "https://dashboard.example.com/register-new-totem",
            400,
            "Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"message":"Totem already exists"}'),
        )

        with mock.patch("pi_kiosk.linux._machine_id", return_value="machine-123"):
            with mock.patch("urllib.request.urlopen", side_effect=http_error):
                with self.assertRaisesRegex(
                    UserFacingError,
                    "HTTP 400: Totem already exists",
                ):
                    host.register_totem(
                        "https://dashboard.example.com/register-new-totem",
                        "totem-secret",
                        "minipc-07",
                        "video",
                        "Hall Screen",
                        "Main entrance display",
                        "Reception",
                        TotemConnectionDetails(
                            rustdesk_id=None,
                            rustdesk_password=None,
                        ),
                    )

    def test_install_totem_status_reporter_writes_files_and_enables_timer(self):
        host = LinuxHost()
        config = TotemStatusReporterConfig(
            endpoint_url="https://dashboard.example.com/totem-status",
            token="status-secret",
            totem_id="minipc-07",
            totem_type="video",
            desktop_user="kiosk",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "usr" / "local" / "lib" / "pi-kiosk" / "totem-status.py"
            status_config = root / "etc" / "pi-kiosk" / "totem-status.json"
            service = root / "etc" / "systemd" / "system" / "pi-kiosk-totem-status.service"
            timer = root / "etc" / "systemd" / "system" / "pi-kiosk-totem-status.timer"

            with mock.patch("pi_kiosk.linux.status_script_path", return_value=script):
                with mock.patch("pi_kiosk.linux.status_config_path", return_value=status_config):
                    with mock.patch("pi_kiosk.linux.status_service_path", return_value=service):
                        with mock.patch("pi_kiosk.linux.status_timer_path", return_value=timer):
                            with mock.patch.object(host, "run") as run:
                                host.install_totem_status_reporter(config)
                                self.assertTrue(script.is_file())
                                self.assertEqual(script.stat().st_mode & 0o777, 0o755)
                                self.assertIn(
                                    '"totem_type": config["totemType"]',
                                    script.read_text(encoding="utf-8"),
                                )
                                self.assertIn(
                                    '"kiosk_running": kiosk_running',
                                    script.read_text(encoding="utf-8"),
                                )
                                self.assertIn(
                                    '"totemType": "video"',
                                    status_config.read_text(encoding="utf-8"),
                                )
                                self.assertIn(
                                    '"webapp_running": webapp_running',
                                    script.read_text(encoding="utf-8"),
                                )
                                self.assertIn(
                                    "socket.gethostname().strip()",
                                    script.read_text(encoding="utf-8"),
                                )
                                self.assertEqual(
                                    json.loads(status_config.read_text(encoding="utf-8")),
                                    {
                                        "endpointUrl": "https://dashboard.example.com/totem-status",
                                        "token": "status-secret",
                                        "totemId": "minipc-07",
                                        "totemType": "video",
                                        "desktopUser": "kiosk",
                                        "port": 8080,
                                    },
                                )
                                self.assertIn(
                                    "ExecStart=/usr/bin/python3",
                                    service.read_text(encoding="utf-8"),
                                )
                                self.assertIn(
                                    "OnUnitActiveSec=1h",
                                    timer.read_text(encoding="utf-8"),
                                )
                                run.assert_has_calls(
                                    [
                                        mock.call(["systemctl", "daemon-reload"]),
                                        mock.call(
                                            ["systemctl", "enable", "--now", "pi-kiosk-totem-status.timer"]
                                        ),
                                        mock.call(
                                            ["systemctl", "start", "pi-kiosk-totem-status.service"],
                                            check=False,
                                        ),
                                    ]
                                )

    def test_install_totem_status_reporter_returns_warning_when_first_run_fails(self):
        host = LinuxHost()
        config = TotemStatusReporterConfig(
            endpoint_url="https://dashboard.example.com/totem-status",
            token="status-secret",
            totem_id="minipc-07",
            totem_type="video",
            desktop_user="kiosk",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "usr" / "local" / "lib" / "pi-kiosk" / "totem-status.py"
            status_config = root / "etc" / "pi-kiosk" / "totem-status.json"
            service = root / "etc" / "systemd" / "system" / "pi-kiosk-totem-status.service"
            timer = root / "etc" / "systemd" / "system" / "pi-kiosk-totem-status.timer"

            with mock.patch("pi_kiosk.linux.status_script_path", return_value=script):
                with mock.patch("pi_kiosk.linux.status_config_path", return_value=status_config):
                    with mock.patch("pi_kiosk.linux.status_service_path", return_value=service):
                        with mock.patch("pi_kiosk.linux.status_timer_path", return_value=timer):
                            with mock.patch.object(
                                host,
                                "run",
                                side_effect=[
                                    subprocess.CompletedProcess(
                                        ["systemctl", "daemon-reload"], 0
                                    ),
                                    subprocess.CompletedProcess(
                                        ["systemctl", "enable", "--now", "pi-kiosk-totem-status.timer"],
                                        0,
                                    ),
                                    subprocess.CompletedProcess(
                                        ["systemctl", "start", "pi-kiosk-totem-status.service"],
                                        1,
                                    ),
                                ],
                            ) as run:
                                warning = host.install_totem_status_reporter(config)

        self.assertIsNotNone(warning)
        self.assertIn("first status run failed", warning)
        self.assertIn("journalctl -u pi-kiosk-totem-status.service", warning)
        run.assert_has_calls(
            [
                mock.call(["systemctl", "daemon-reload"]),
                mock.call(["systemctl", "enable", "--now", "pi-kiosk-totem-status.timer"]),
                mock.call(["systemctl", "start", "pi-kiosk-totem-status.service"], check=False),
            ]
        )

if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import getpass
import json
import os
import pwd
import shlex
import shutil
import socket
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib import error, request
from urllib.parse import unquote, urlparse
import zipfile

from pi_kiosk.detect import looks_like_raspberry_pi
from pi_kiosk.errors import UserFacingError
from pi_kiosk.host import (
    RustDeskInstall,
    TotemConnectionDetails,
    TotemStatusReporterConfig,
    VideoDeployment,
    VideoSource,
    WebAppDeployment,
    WebAppSource,
)
from pi_kiosk.totem_status import (
    reporter_config_json,
    reporter_script,
    service_unit,
    status_config_path,
    status_script_path,
    status_service_path,
    status_timer_path,
    timer_unit,
)


class NeedSudoUser(RuntimeError):
    """The tool must know which desktop user's home to modify."""


RUSTDESK_CREDENTIALS_PATH = Path("/etc/pi-kiosk/rustdesk.json")
RUSTDESK_PASSWORD_SUCCESS_TEXT = "Done!"
RUSTDESK_UNATTENDED_OPTIONS = (
    ("approve-mode", "password"),
    ("verification-method", "use-permanent-password"),
)

_WEBAPP_LOCKDOWN = """\
<style id="pi-kiosk-lockdown">
  * { -webkit-user-select: none !important; user-select: none !important; -webkit-touch-callout: none !important; }
</style>
<script>
  window.addEventListener("contextmenu", event => event.preventDefault(), true);
</script>
"""


def _lock_down_webapp(app_root: Path) -> None:
    for path in app_root.rglob("*.html"):
        html = path.read_text(encoding="utf-8")
        if 'id="pi-kiosk-lockdown"' in html:
            continue
        head = html.lower().find("<head")
        insertion = html.find(">", head) + 1 if head >= 0 else 0
        path.write_text(
            f"{html[:insertion]}\n{_WEBAPP_LOCKDOWN}{html[insertion:]}",
            encoding="utf-8",
        )


class WebAppDeployer:
    def __init__(self, host: LinuxHost) -> None:
        self._host = host

    def deploy(
        self,
        source: WebAppSource,
        progress: Callable[[str], None] | None = None,
    ) -> WebAppDeployment:
        self._host._report_progress(progress, "Preparing webapp ZIP download")
        app_root = Path(self._host.home()) / ".local" / "share" / "pi-kiosk" / "webapp"
        current_dir = app_root / "current"
        app_root.mkdir(parents=True, exist_ok=True)
        self._host._own_within_home(app_root)

        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            archive_path = temp_root / "webapp-release.zip"
            self._host._report_progress(progress, "Downloading webapp ZIP")
            self._host._download_file(
                source.release_url,
                archive_path,
                description="webapp ZIP",
                progress=progress,
            )
            self._host._report_progress(progress, "Extracting webapp files")
            extracted_root = temp_root / "webapp-release"
            extracted_root.mkdir(parents=True, exist_ok=True)
            self._host._extract_webapp_zip(archive_path, extracted_root)
            source_root = self._host._resolve_webapp_root(extracted_root)
            stage_dir = app_root / "next"
            if stage_dir.exists():
                shutil.rmtree(stage_dir)
            stage_dir.mkdir(parents=True, exist_ok=True)
            self._host._report_progress(progress, "Deploying webapp files")
            self._host._copy_directory_contents(source_root, stage_dir)
            _lock_down_webapp(stage_dir)
            if current_dir.exists():
                shutil.rmtree(current_dir)
            stage_dir.replace(current_dir)

        self._host._own_tree(current_dir)
        return WebAppDeployment(
            source_url=source.release_url,
            app_dir=str(current_dir),
        )


class VideoDeployer:
    def __init__(self, host: LinuxHost) -> None:
        self._host = host

    def deploy(
        self,
        source: VideoSource,
        progress: Callable[[str], None] | None = None,
    ) -> VideoDeployment:
        video_root = Path(self._host.home()) / ".local" / "share" / "pi-kiosk" / "video"
        current_dir = video_root / "current"
        video_root.mkdir(parents=True, exist_ok=True)
        self._host._own_within_home(video_root)

        with tempfile.TemporaryDirectory():
            self._host._report_progress(progress, "Preparing Dropbox download")
            file_name = _video_file_name(source.download_url)
            stage_dir = video_root / "next"
            if stage_dir.exists():
                shutil.rmtree(stage_dir)
            stage_dir.mkdir(parents=True, exist_ok=True)

            video_path = self._host._download_video_file(
                source.download_url,
                stage_dir,
                default_file_name=file_name,
                progress=progress,
            )
            if video_path.stat().st_size == 0:
                raise UserFacingError("Downloaded video file was empty.")

            self._host._report_progress(progress, "Deploying video file")
            if current_dir.exists():
                shutil.rmtree(current_dir)
            stage_dir.replace(current_dir)

        self._host._own_tree(current_dir)
        deployed_path = current_dir / video_path.name
        return VideoDeployment(
            video_path=str(deployed_path),
            file_name=video_path.name,
        )


class RustDeskService:
    def __init__(self, host: LinuxHost) -> None:
        self._host = host

    def install(
        self,
        password: str,
        progress: Callable[[str], None] | None = None,
    ) -> RustDeskInstall:
        self._host._report_progress(progress, "Resolving latest RustDesk release")
        release = self._host._read_json(
            "https://api.github.com/repos/rustdesk/rustdesk/releases/latest"
        )
        asset = _select_rustdesk_deb_asset(release, self._host._debian_architecture())

        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            package_path = temp_root / asset["name"]

            self._host._report_progress(progress, "Downloading RustDesk package")
            self._host._download_file(
                str(asset["browser_download_url"]),
                package_path,
                description="RustDesk package",
            )

            self._host._report_progress(progress, "Installing RustDesk package")
            subprocess.run(
                ["apt-get", "install", "-fy", str(package_path)],
                check=True,
                text=True,
            )

        self._host._report_progress(progress, "Configuring RustDesk access")
        self._host._restart_rustdesk_service()
        rustdesk_id = self._host._rustdesk_get_id()
        self.configure_password(password)

        return RustDeskInstall(
            rustdesk_id=rustdesk_id,
            asset_name=str(asset["name"]),
        )

    def installed(self) -> bool:
        return shutil.which("rustdesk") is not None

    def configure_password(self, password: str) -> None:
        failure = self._configure_unattended_access(password)
        if failure is not None:
            launch_failure = self._start_user_server()
            if launch_failure is None:
                time.sleep(1)
                failure = self._configure_unattended_access(password)
            else:
                failure = f"{failure}{launch_failure} "
        if failure is not None:
            raise UserFacingError(
                "RustDesk did not confirm the unattended-access configuration. "
                f"{failure} Open RustDesk once in the desktop session and run the setup again."
            )
        _save_rustdesk_password(password)
        self._host._restart_rustdesk_service()

    def connection_details(
        self,
        rustdesk_password: str | None = None,
    ) -> TotemConnectionDetails:
        return TotemConnectionDetails(
            rustdesk_id=_rustdesk_id(),
            rustdesk_password=(
                rustdesk_password
                if rustdesk_password is not None
                else _saved_rustdesk_password()
            ),
        )

    def _configure_unattended_access(self, password: str) -> str | None:
        failures: list[str] = []

        for option_name, expected_value in RUSTDESK_UNATTENDED_OPTIONS:
            self._run_rustdesk_command(["--option", option_name, expected_value])
            result = self._run_rustdesk_command(["--option", option_name])
            current_value = result.stdout.strip()
            if current_value != expected_value:
                actual = current_value or "empty"
                failures.append(
                    f"RustDesk kept {option_name}={actual} instead of {expected_value}."
                )

        result = self._run_rustdesk_command(["--password", password])
        if result.stdout.strip() != RUSTDESK_PASSWORD_SUCCESS_TEXT:
            detail = _subprocess_result_detail(result)
            if detail:
                failures.append(f"RustDesk password command said: {detail}.")
            else:
                failures.append("RustDesk did not report a successful password update.")

        if failures:
            return " ".join(failures) + " "
        return None

    def _run_rustdesk_command(
        self,
        argv: list[str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["rustdesk", *argv],
            check=True,
            text=True,
            capture_output=True,
        )

    def _start_user_server(self) -> str | None:
        result = self._host.run_in_desktop_session(
            [
                "sh",
                "-lc",
                "nohup rustdesk --server >/dev/null 2>&1 </dev/null &",
            ],
            check=False,
        )
        if result.returncode == 0:
            return
        detail = _subprocess_result_detail(result)
        if detail:
            return f"Could not start RustDesk in the desktop session: {detail}."
        return "Could not start RustDesk in the desktop session."


class TotemRegistrationClient:
    def register(
        self,
        endpoint_url: str,
        token: str,
        machine_name: str,
        totem_type: str,
        totem_name: str,
        description: str,
        location: str,
        connection: TotemConnectionDetails,
    ) -> None:
        payload = {
            "totem_id": machine_name,
            "totemType": totem_type,
            "machineName": machine_name,
            "machineId": _machine_id(),
            "name": totem_name,
            "description": description,
            "location": location,
            "rustdeskId": connection.rustdesk_id,
            "rustdeskPassword": connection.rustdesk_password,
            "registeredAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        req = request.Request(
            endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=5) as response:
                status = response.getcode()
        except error.HTTPError as exc:
            detail = _http_error_detail(exc)
            if detail:
                raise UserFacingError(
                    f"Totem registration failed with HTTP {exc.code}: {detail}."
                ) from exc
            raise UserFacingError(f"Totem registration failed with HTTP {exc.code}.") from exc
        except error.URLError as exc:
            raise UserFacingError(f"Totem registration failed: {exc.reason}.") from exc

        if status < 200 or status >= 300:
            raise UserFacingError(f"Totem registration failed with HTTP {status}.")


class TotemStatusReporterInstaller:
    def __init__(self, host: LinuxHost) -> None:
        self._host = host

    def install(
        self,
        config: TotemStatusReporterConfig,
    ) -> str | None:
        script_path = status_script_path()
        config_path = status_config_path()
        service_path = status_service_path()
        timer_path = status_timer_path()

        script_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        service_path.parent.mkdir(parents=True, exist_ok=True)

        script_path.write_text(reporter_script(), encoding="utf-8")
        script_path.chmod(0o755)
        config_path.write_text(reporter_config_json(config), encoding="utf-8")
        service_path.write_text(service_unit(), encoding="utf-8")
        timer_path.write_text(timer_unit(), encoding="utf-8")

        self._host.run(["systemctl", "daemon-reload"])
        self._host.run(["systemctl", "enable", "--now", timer_path.name])
        result = self._host.run(["systemctl", "start", service_path.name], check=False)
        if result.returncode != 0:
            return (
                "Status reporter was installed, but the first status run failed. "
                f"The timer remains enabled. Check `systemctl status {service_path.name}` "
                f"and `journalctl -u {service_path.name} -n 50 --no-pager`."
            )
        return None


class LinuxHost:
    """Talks to the real machine. Keep this thin; logic lives in the steps."""

    def __init__(self) -> None:
        self._webapp_deployer = WebAppDeployer(self)
        self._video_deployer = VideoDeployer(self)
        self._rustdesk_service = RustDeskService(self)
        self._totem_registration = TotemRegistrationClient()
        self._status_reporter_installer = TotemStatusReporterInstaller(self)

    def home(self) -> str:
        return str(Path(pwd.getpwnam(self.user()).pw_dir))

    def user(self) -> str:
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            return sudo_user
        if self.is_root():
            raise NeedSudoUser(
                "Run this tool with sudo from the desktop user account. "
                "Nothing was changed."
            )
        return getpass.getuser()

    def machine_name(self) -> str:
        return socket.gethostname()

    def is_raspberry_pi(self) -> bool:
        return looks_like_raspberry_pi(
            model=_read_device_tree_model(),
            has_rpi_issue=Path("/etc/rpi-issue").is_file(),
        )

    def is_root(self) -> bool:
        return os.geteuid() == 0

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def mkdir(self, path: str) -> None:
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        self._own_within_home(directory)

    def read_file(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._own_within_home(target.parent)
        target.write_text(content, encoding="utf-8")
        if target.name == "autostart":
            target.chmod(0o755)
        self._own(target)

    def detect_wayland_output(self) -> str | None:
        result = self.run_in_desktop_session(["wlr-randr"], check=False)
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if line and not line[0].isspace():
                return line.split()[0]
        return None

    def run(self, argv: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, check=check, text=True)

    def run_in_desktop_session(
        self,
        argv: list[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = self._desktop_session_env()
        if env is None:
            result = subprocess.CompletedProcess(
                args=list(argv),
                returncode=1,
                stdout="",
                stderr="No desktop Wayland session detected.",
            )
            if check:
                raise subprocess.CalledProcessError(
                    result.returncode,
                    argv,
                    output=result.stdout,
                    stderr=result.stderr,
                )
            return result

        if self.is_root():
            command = ["sudo", "-H", "-u", self.user(), "env"]
            command.extend(f"{name}={value}" for name, value in env.items())
            command.extend(argv)
            return subprocess.run(
                command,
                check=check,
                text=True,
                capture_output=True,
            )

        merged_env = os.environ.copy()
        merged_env.update(env)
        return subprocess.run(
            argv,
            check=check,
            text=True,
            capture_output=True,
            env=merged_env,
        )

    def deploy_webapp(
        self,
        source: WebAppSource,
        progress: Callable[[str], None] | None = None,
    ) -> WebAppDeployment:
        return self._webapp_deployer.deploy(source, progress)

    def chromium_command(self) -> str | None:
        for candidate in ("chromium-browser", "chromium"):
            found = shutil.which(candidate)
            if found:
                return found
        return None

    def deploy_video(
        self,
        source: VideoSource,
        progress: Callable[[str], None] | None = None,
    ) -> VideoDeployment:
        return self._video_deployer.deploy(source, progress)

    def mpv_command(self) -> str | None:
        return shutil.which("mpv")

    def wtype_command(self) -> str | None:
        return shutil.which("wtype")

    def swayidle_command(self) -> str | None:
        return shutil.which("swayidle")

    def ensure_packages_installed(self, packages: tuple[str, ...]) -> None:
        subprocess.run(
            ["apt-get", "install", "-y", *packages],
            check=True,
            text=True,
        )

    def launch_kiosk_now(self, launcher: str) -> None:
        command = [
            "sh",
            "-lc",
            " ".join(
                [
                    "labwc --reconfigure >/dev/null 2>&1 || true;",
                    "sleep 1;",
                    f"nohup bash {shlex.quote(launcher)} >/dev/null 2>&1 </dev/null &",
                ]
            ),
        ]
        self.run_in_desktop_session(command, check=True)

    def launch_webapp_server_now(self, launcher: str) -> None:
        command = [
            "sh",
            "-lc",
            f"nohup bash {shlex.quote(launcher)} server-only >/dev/null 2>&1 </dev/null &",
        ]
        self.run_in_desktop_session(command, check=True)

    def launch_video_now(self, launcher: str) -> None:
        self.launch_kiosk_now(launcher)

    def reboot(self) -> None:
        subprocess.run(["reboot"], check=True, text=True)

    def touchscreen_present(self) -> bool:
        try:
            result = subprocess.run(
                ["libinput", "list-devices"],
                check=False,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError:
            return False
        return _libinput_reports_touch(result.stdout)

    def install_rustdesk(
        self,
        password: str,
        progress: Callable[[str], None] | None = None,
    ) -> RustDeskInstall:
        return self._rustdesk_service.install(password, progress)

    def rustdesk_installed(self) -> bool:
        return self._rustdesk_service.installed()

    def configure_rustdesk_password(self, password: str) -> None:
        self._rustdesk_service.configure_password(password)

    def connection_details(
        self,
        rustdesk_password: str | None = None,
    ) -> TotemConnectionDetails:
        return self._rustdesk_service.connection_details(rustdesk_password)

    def register_totem(
        self,
        endpoint_url: str,
        token: str,
        machine_name: str,
        totem_type: str,
        totem_name: str,
        description: str,
        location: str,
        connection: TotemConnectionDetails,
    ) -> None:
        self._totem_registration.register(
            endpoint_url,
            token,
            machine_name,
            totem_type,
            totem_name,
            description,
            location,
            connection,
        )

    def install_totem_status_reporter(
        self,
        config: TotemStatusReporterConfig,
    ) -> str | None:
        return self._status_reporter_installer.install(config)

    def _own(self, path: Path) -> None:
        if not self.is_root():
            return
        try:
            info = pwd.getpwnam(self.user())
        except KeyError:
            return
        os.chown(path, info.pw_uid, info.pw_gid)

    def _own_within_home(self, path: Path) -> None:
        home = Path(self.home())
        current = path
        while current == home or home in current.parents:
            self._own(current)
            if current == home:
                break
            current = current.parent

    def _desktop_session_env(self) -> dict[str, str] | None:
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        term = os.environ.get("TERM")
        home = self.home()

        if self.is_root():
            user_info = pwd.getpwnam(self.user())
            runtime_dir = runtime_dir or f"/run/user/{user_info.pw_uid}"
            home = user_info.pw_dir

        if not runtime_dir:
            return None

        runtime_path = Path(runtime_dir)
        if not runtime_path.is_dir():
            return None

        if not wayland_display:
            sockets = sorted(runtime_path.glob("wayland-*"))
            if not sockets:
                return None
            wayland_display = sockets[0].name

        env = {
            "XDG_RUNTIME_DIR": str(runtime_path),
            "WAYLAND_DISPLAY": wayland_display,
        }
        if home:
            env["HOME"] = home
        bus_path = runtime_path / "bus"
        if bus_path.exists():
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"
        if term:
            env["TERM"] = term
        return env

    def _read_json(self, url: str) -> dict[str, object]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "pi-kiosk-setup",
        }
        req = request.Request(url, headers=headers)
        try:
            with request.urlopen(req) as response:
                return json.load(response)
        except error.HTTPError as exc:
            if exc.code == 404:
                raise UserFacingError("GitHub resource was not found.") from exc
            raise UserFacingError(f"GitHub API request failed with HTTP {exc.code}.") from exc
        except error.URLError as exc:
            raise UserFacingError(f"Could not reach GitHub: {exc.reason}.") from exc

    def _download_file(
        self,
        url: str,
        target: Path,
        description: str = "file",
        progress: Callable[[str], None] | None = None,
    ) -> None:
        headers = {"User-Agent": "pi-kiosk-setup"}
        req = request.Request(url, headers=headers)
        try:
            with request.urlopen(req) as response, target.open("wb") as stream:
                self._copy_response_body(
                    response,
                    stream,
                    description=description,
                    progress=progress,
                )
        except error.HTTPError as exc:
            raise UserFacingError(f"Failed to download the {description} (HTTP {exc.code}).") from exc
        except error.URLError as exc:
            raise UserFacingError(f"Could not download the {description}: {exc.reason}.") from exc

    def _download_video_file(
        self,
        url: str,
        target_dir: Path,
        default_file_name: str,
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        headers = {"User-Agent": "pi-kiosk-setup"}
        req = request.Request(url, headers=headers)
        try:
            with request.urlopen(req) as response:
                _validate_video_content_type(response)
                file_name = _content_disposition_filename(response) or default_file_name
                target = target_dir / file_name
                with target.open("wb") as stream:
                    bytes_written = self._copy_response_body(
                        response,
                        stream,
                        description="video file",
                        progress=progress,
                    )
                expected_size = _content_length(response)
                if expected_size is not None and bytes_written != expected_size:
                    raise UserFacingError(
                        f"Downloaded video file was incomplete: expected {expected_size} bytes "
                        f"but received {bytes_written}."
                    )
                if bytes_written == 0:
                    raise UserFacingError("Downloaded video file was empty.")
                return target
        except error.HTTPError as exc:
            raise UserFacingError(f"Failed to download the video file (HTTP {exc.code}).") from exc
        except error.URLError as exc:
            raise UserFacingError(f"Could not download the video file: {exc.reason}.") from exc

    def _copy_response_body(
        self,
        response: object,
        stream: object,
        description: str,
        progress: Callable[[str], None] | None = None,
    ) -> int:
        total_size = _content_length(response)
        bytes_written = 0
        if total_size is not None and total_size > 0:
            self._report_progress(progress, f"Downloading {description} (0%)")
            last_reported = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                stream.write(chunk)
                bytes_written += len(chunk)
                percent = min(100, int(bytes_written * 100 / total_size))
                if percent >= last_reported + 5 or percent == 100:
                    self._report_progress(progress, f"Downloading {description} ({percent}%)")
                    last_reported = percent
            return bytes_written

        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            stream.write(chunk)
            bytes_written += len(chunk)
        return bytes_written

    def _extract_webapp_zip(self, archive_path: Path, target_dir: Path) -> None:
        try:
            with zipfile.ZipFile(archive_path) as bundle:
                members = bundle.infolist()
                if not members:
                    raise UserFacingError("Downloaded webapp ZIP was empty.")

                for member in members:
                    if _zip_info_is_symlink(member):
                        raise UserFacingError(
                            "Webapp ZIP contained a symbolic link, which is not supported."
                        )

                    relative = _safe_zip_member_path(member.filename)
                    if relative is None:
                        continue

                    destination = target_dir / relative
                    if member.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue

                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source_stream, destination.open("wb") as target_stream:
                        shutil.copyfileobj(source_stream, target_stream)
        except zipfile.BadZipFile as exc:
            raise UserFacingError("Downloaded webapp ZIP was not a valid zip archive.") from exc
        except (OSError, RuntimeError) as exc:
            raise UserFacingError(f"Could not extract the webapp ZIP: {exc}.") from exc

    def _resolve_webapp_root(self, extracted_root: Path) -> Path:
        current_root = extracted_root
        while True:
            entries = [
                entry for entry in current_root.iterdir() if not _ignore_webapp_bundle_entry(entry.name)
            ]
            if not entries:
                raise UserFacingError("Downloaded webapp ZIP was empty.")

            if (current_root / "index.html").is_file():
                return current_root

            if len(entries) == 1 and entries[0].is_dir():
                current_root = entries[0]
                continue

            raise UserFacingError(
                "Webapp ZIP did not contain index.html at the archive root. "
                "Package the built webapp files directly in the zip and run the wizard again."
            )

    def _copy_directory_contents(self, source: Path, target: Path) -> None:
        for child in source.iterdir():
            destination = target / child.name
            if child.is_dir():
                shutil.copytree(child, destination)
            else:
                shutil.copy2(child, destination)

    def _own_tree(self, root: Path) -> None:
        self._own_within_home(root)
        for child in root.rglob("*"):
            self._own(child)

    def _report_progress(
        self,
        progress: Callable[[str], None] | None,
        message: str,
    ) -> None:
        if progress is not None:
            progress(message)

    def _debian_architecture(self) -> str:
        result = subprocess.run(
            ["dpkg", "--print-architecture"],
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()

    def _restart_rustdesk_service(self) -> None:
        subprocess.run(
            ["systemctl", "restart", "rustdesk"],
            check=False,
            text=True,
        )

    def _rustdesk_get_id(self) -> str:
        result = subprocess.run(
            ["rustdesk", "--get-id"],
            check=True,
            text=True,
            capture_output=True,
        )
        rustdesk_id = result.stdout.strip()
        if not rustdesk_id:
            raise UserFacingError("RustDesk did not return an ID after installation.")
        return rustdesk_id


def _http_error_detail(exc: error.HTTPError) -> str:
    try:
        payload = exc.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""

    if not payload:
        return ""

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        for key in ("message", "error", "detail"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().rstrip(".")
        errors = data.get("errors")
        if isinstance(errors, list):
            messages = [
                item.strip().rstrip(".")
                for item in errors
                if isinstance(item, str) and item.strip()
            ]
            if messages:
                return "; ".join(messages)

    compact = " ".join(payload.split()).rstrip(".")
    if len(compact) > 200:
        return compact[:197] + "..."
    return compact


def _subprocess_result_detail(result: subprocess.CompletedProcess[str]) -> str:
    parts = [value.strip() for value in (result.stdout, result.stderr) if value.strip()]
    return " ".join(parts)


def _rustdesk_id() -> str | None:
    try:
        result = subprocess.run(
            ["rustdesk", "--get-id"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _save_rustdesk_password(password: str) -> None:
    RUSTDESK_CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUSTDESK_CREDENTIALS_PATH.write_text(
        json.dumps({"password": password}),
        encoding="utf-8",
    )
    RUSTDESK_CREDENTIALS_PATH.chmod(0o600)


def _saved_rustdesk_password() -> str | None:
    if not RUSTDESK_CREDENTIALS_PATH.is_file():
        return None
    try:
        data = json.loads(RUSTDESK_CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("password")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _read_device_tree_model() -> str | None:
    for candidate in (
        Path("/proc/device-tree/model"),
        Path("/sys/firmware/devicetree/base/model"),
    ):
        try:
            raw = candidate.read_bytes()
        except OSError:
            continue
        return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
    return None


def _safe_zip_member_path(name: str) -> Path | None:
    path = PurePosixPath(name)
    if path.is_absolute():
        raise UserFacingError("Webapp ZIP contained an unsafe absolute path.")

    parts: list[str] = []
    for part in path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise UserFacingError("Webapp ZIP contained an unsafe parent path.")
        parts.append(part)

    if not parts:
        return None
    return Path(*parts)


def _zip_info_is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _ignore_webapp_bundle_entry(name: str) -> bool:
    return name in {"__MACOSX", ".DS_Store"}


def _machine_id() -> str | None:
    path = Path("/etc/machine-id")
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _libinput_reports_touch(stdout: str) -> bool:
    for line in stdout.splitlines():
        if line.lstrip().startswith("Capabilities:") and "touch" in line.lower():
            return True
    return False


def _video_file_name(url: str) -> str:
    path = urlparse(url).path
    name = Path(unquote(path)).name
    return name or "video.bin"


def _content_length(response: object) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("Content-Length")
    if value is None:
        return None
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    return size


def _header_value(response: object, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get(name)
    if not isinstance(value, str):
        return None
    return value


def _normalized_content_type(response: object) -> str | None:
    value = _header_value(response, "Content-Type")
    if value is None:
        return None
    return value.split(";", 1)[0].strip().lower()


def _validate_video_content_type(response: object) -> None:
    content_type = _normalized_content_type(response)
    if content_type is None:
        return
    if content_type.startswith("video/"):
        return
    if content_type in {
        "application/octet-stream",
        "binary/octet-stream",
        "application/mp4",
        "application/x-mp4",
    }:
        return
    raise UserFacingError(
        f"Dropbox did not return a video file. Got Content-Type {content_type}."
    )


def _content_disposition_filename(response: object) -> str | None:
    value = _header_value(response, "Content-Disposition")
    if value is None:
        return None
    for part in value.split(";")[1:]:
        item = part.strip()
        lower = item.lower()
        if lower.startswith("filename*="):
            encoded = item.split("=", 1)[1].strip().strip('"')
            if "''" in encoded:
                _, encoded = encoded.split("''", 1)
            return _safe_download_filename(unquote(encoded))
        if lower.startswith("filename="):
            return _safe_download_filename(item.split("=", 1)[1].strip().strip('"'))
    return None


def _safe_download_filename(value: str) -> str | None:
    name = Path(value).name.strip()
    if not name:
        return None
    return name


def _select_rustdesk_deb_asset(release: dict[str, object], arch: str) -> dict[str, str]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UserFacingError("RustDesk release metadata did not include assets.")

    suffixes = _rustdesk_asset_suffixes(arch)
    for suffix in suffixes:
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            url = asset.get("browser_download_url")
            if isinstance(name, str) and isinstance(url, str) and name.endswith(suffix):
                return {"name": name, "browser_download_url": url}

    raise UserFacingError(
        f"No supported RustDesk .deb package was found for architecture {arch}."
    )


def _rustdesk_asset_suffixes(arch: str) -> tuple[str, ...]:
    mapping = {
        "arm64": ("aarch64.deb",),
        "armhf": ("armv7-sciter.deb", "armv7.deb"),
        "amd64": ("x86_64.deb", "amd64.deb"),
    }
    return mapping.get(arch, ())

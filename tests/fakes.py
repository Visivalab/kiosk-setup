from dataclasses import dataclass
from typing import Callable

from pi_kiosk.host import (
    RustDeskInstall,
    TotemConnectionDetails,
    TotemStatusReporterConfig,
    VideoDeployment,
    VideoSource,
    WebAppDeployment,
    WebAppSource,
)

DEMO_RELEASE_URL = (
    "https://visivalab-totems-releases.s3.eu-west-3.amazonaws.com/"
    "demo-app/demo-app-dist.zip"
)


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeHost:
    """In-memory host. Tests never touch the real machine."""

    def __init__(
        self,
        *,
        home: str = "/home/pi",
        user: str = "pi",
        machine_name: str = "pi-kiosk-01",
        files: dict[str, str] | None = None,
        wayland_output: str | None = "HDMI-A-1",
        raspberry_pi: bool = True,
        root: bool = True,
        desktop_session_returncode: int = 0,
        deployed_webapp: WebAppDeployment | None = None,
        deployed_video: VideoDeployment | None = None,
        chromium: str | None = "chromium-browser",
        mpv: str | None = "/usr/bin/mpv",
        wtype: str | None = "/usr/bin/wtype",
        swayidle: str | None = "/usr/bin/swayidle",
        touchscreen: bool = False,
        rustdesk_install: RustDeskInstall | None = None,
        saved_rustdesk_password: str | None = None,
        rustdesk_present: bool = True,
    ) -> None:
        self.home_dir = home
        self.username = user
        self.machine = machine_name
        self.files: dict[str, str] = dict(files or {})
        self.wayland_output = wayland_output
        self.raspberry_pi = raspberry_pi
        self.root = root
        self.desktop_session_returncode = desktop_session_returncode
        self.deployed_webapp = deployed_webapp or WebAppDeployment(
            source_url=DEMO_RELEASE_URL,
            app_dir=f"{home}/.local/share/pi-kiosk/webapp/current",
        )
        self.deployed_video = deployed_video or VideoDeployment(
            video_path=f"{home}/.local/share/pi-kiosk/video/current/demo.mp4",
            file_name="demo.mp4",
        )
        self.chromium = chromium
        self.mpv = mpv
        self.wtype = wtype
        self.swayidle = swayidle
        self.touchscreen = touchscreen
        self.rustdesk_install = rustdesk_install or RustDeskInstall(
            rustdesk_id="123 456 789",
            asset_name="rustdesk-1.4.3-aarch64.deb",
        )
        self.saved_rustdesk_password = saved_rustdesk_password
        self.rustdesk_present = rustdesk_present
        self.commands: list[list[str]] = []
        self.desktop_session_commands: list[list[str]] = []
        self.webapp_deploy_requests: list[WebAppSource] = []
        self.webapp_progress_messages: list[str] = []
        self.video_deploy_requests: list[VideoSource] = []
        self.video_progress_messages: list[str] = []
        self.launched_kiosk_paths: list[str] = []
        self.launched_server_paths: list[str] = []
        self.launched_video_paths: list[str] = []
        self.rebooted = False
        self.rustdesk_progress_messages: list[str] = []
        self.rustdesk_passwords: list[str] = []
        self.configured_rustdesk_passwords: list[str] = []
        self.installed_packages: list[tuple[str, ...]] = []
        self.directories: set[str] = set()
        self.totem_registration_requests: list[dict[str, str]] = []
        self.totem_status_reporter_installs: list[TotemStatusReporterConfig] = []
        self.connection_details_requests: list[str | None] = []

    def home(self) -> str:
        return self.home_dir

    def user(self) -> str:
        return self.username

    def machine_name(self) -> str:
        return self.machine

    def is_raspberry_pi(self) -> bool:
        return self.raspberry_pi

    def is_root(self) -> bool:
        return self.root

    def exists(self, path: str) -> bool:
        if path in self.files:
            return True
        return any(entry.startswith(path.rstrip("/") + "/") for entry in self.files)

    def mkdir(self, path: str) -> None:
        self.directories.add(path)

    def read_file(self, path: str) -> str:
        try:
            return self.files[path]
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    def write_file(self, path: str, content: str) -> None:
        parent = path.rsplit("/", 1)[0]
        if parent:
            self.directories.add(parent)
        self.files[path] = content

    def detect_wayland_output(self) -> str | None:
        return self.wayland_output

    def run(self, argv: list[str], check: bool = True) -> CommandResult:
        self.commands.append(list(argv))
        return CommandResult(argv=list(argv), returncode=0)

    def run_in_desktop_session(self, argv: list[str], check: bool = True) -> CommandResult:
        self.desktop_session_commands.append(list(argv))
        return CommandResult(argv=list(argv), returncode=self.desktop_session_returncode)

    def deploy_webapp(
        self,
        source: WebAppSource,
        progress: Callable[[str], None] | None = None,
    ) -> WebAppDeployment:
        self.webapp_deploy_requests.append(source)
        if progress is not None:
            for message in (
                "Preparing webapp ZIP download",
                "Downloading webapp ZIP",
                "Extracting webapp files",
                "Deploying webapp files",
            ):
                progress(message)
                self.webapp_progress_messages.append(message)
        return self.deployed_webapp

    def deploy_video(
        self,
        source: VideoSource,
        progress: Callable[[str], None] | None = None,
    ) -> VideoDeployment:
        self.video_deploy_requests.append(source)
        if progress is not None:
            for message in (
                "Preparing Dropbox download",
                "Downloading video file (0%)",
                "Downloading video file (100%)",
                "Deploying video file",
            ):
                progress(message)
                self.video_progress_messages.append(message)
        return self.deployed_video

    def chromium_command(self) -> str | None:
        return self.chromium

    def mpv_command(self) -> str | None:
        return self.mpv

    def wtype_command(self) -> str | None:
        return self.wtype

    def swayidle_command(self) -> str | None:
        return self.swayidle

    def ensure_packages_installed(self, packages: tuple[str, ...]) -> None:
        self.installed_packages.append(packages)
        if "mpv" in packages and self.mpv is None:
            self.mpv = "/usr/bin/mpv"
        if "wtype" in packages and self.wtype is None:
            self.wtype = "/usr/bin/wtype"
        if "swayidle" in packages and self.swayidle is None:
            self.swayidle = "/usr/bin/swayidle"

    def launch_kiosk_now(self, launcher: str) -> None:
        self.launched_kiosk_paths.append(launcher)

    def launch_webapp_server_now(self, launcher: str) -> None:
        self.launched_server_paths.append(launcher)

    def launch_video_now(self, launcher: str) -> None:
        self.launched_video_paths.append(launcher)

    def reboot(self) -> None:
        self.rebooted = True

    def touchscreen_present(self) -> bool:
        return self.touchscreen

    def install_rustdesk(
        self,
        password: str,
        progress: Callable[[str], None] | None = None,
    ) -> RustDeskInstall:
        self.rustdesk_passwords.append(password)
        self.saved_rustdesk_password = password
        self.rustdesk_present = True
        if progress is not None:
            for message in (
                "Resolving latest RustDesk release",
                "Downloading RustDesk package",
                "Installing RustDesk package",
                "Configuring RustDesk access",
            ):
                progress(message)
                self.rustdesk_progress_messages.append(message)
        return self.rustdesk_install

    def rustdesk_installed(self) -> bool:
        return self.rustdesk_present

    def configure_rustdesk_password(self, password: str) -> None:
        self.configured_rustdesk_passwords.append(password)
        self.saved_rustdesk_password = password

    def connection_details(
        self,
        rustdesk_password: str | None = None,
    ) -> TotemConnectionDetails:
        self.connection_details_requests.append(rustdesk_password)
        return TotemConnectionDetails(
            rustdesk_id=self.rustdesk_install.rustdesk_id if self.rustdesk_present else None,
            rustdesk_password=rustdesk_password
            if rustdesk_password is not None
            else self.saved_rustdesk_password,
        )

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
        self.totem_registration_requests.append(
            {
                "endpoint_url": endpoint_url,
                "token": token,
                "machine_name": machine_name,
                "totem_type": totem_type,
                "totem_name": totem_name,
                "description": description,
                "location": location,
                "connection": connection,
            }
        )

    def install_totem_status_reporter(
        self,
        config: TotemStatusReporterConfig,
    ) -> str | None:
        self.totem_status_reporter_installs.append(config)
        return None

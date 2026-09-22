from dataclasses import dataclass
from typing import Callable
from typing import Protocol


@dataclass(frozen=True)
class WebAppDeployment:
    source_url: str
    app_dir: str
    launcher_path: str = ""
    server_url: str = ""
    log_tail_command: str = ""
    heartbeat_log_tail_command: str = ""
    autostart_configured: bool = False
    chromium_kiosk_configured: bool = False
    cursor_hide_configured: bool = False


@dataclass(frozen=True)
class WebAppSource:
    release_url: str


@dataclass(frozen=True)
class VideoDeployment:
    video_path: str
    file_name: str
    launcher_path: str = ""
    autostart_configured: bool = False
    fullscreen_loop_configured: bool = False


@dataclass(frozen=True)
class VideoSource:
    shared_url: str
    download_url: str


@dataclass(frozen=True)
class RustDeskInstall:
    rustdesk_id: str
    asset_name: str


@dataclass(frozen=True)
class TotemStatusReporterConfig:
    endpoint_url: str
    token: str
    totem_id: str
    totem_type: str
    desktop_user: str


@dataclass(frozen=True)
class TotemConnectionDetails:
    rustdesk_id: str | None
    rustdesk_password: str | None


class UserHost(Protocol):
    def home(self) -> str: ...

    def user(self) -> str: ...

    def machine_name(self) -> str: ...


class GuardHost(Protocol):
    def is_raspberry_pi(self) -> bool: ...

    def is_root(self) -> bool: ...


class FileHost(Protocol):
    def exists(self, path: str) -> bool: ...

    def mkdir(self, path: str) -> None: ...

    def read_file(self, path: str) -> str: ...

    def write_file(self, path: str, content: str) -> None: ...


class RotationHost(UserHost, FileHost, Protocol):
    def detect_wayland_output(self) -> str | None: ...

    def run_in_desktop_session(self, argv: list[str], check: bool = True) -> object: ...


class AutologinHost(UserHost, Protocol):
    def run(self, argv: list[str], check: bool = True) -> object: ...


class NoSleepHost(UserHost, FileHost, Protocol):
    def run(self, argv: list[str], check: bool = True) -> object: ...


class RebootHost(Protocol):
    def reboot(self) -> None: ...


class TouchHost(UserHost, FileHost, Protocol):
    def touchscreen_present(self) -> bool: ...


class PackageHost(Protocol):
    def ensure_packages_installed(self, packages: tuple[str, ...]) -> None: ...


class KioskLaunchHost(RebootHost, Protocol):
    def launch_kiosk_now(self, launcher: str) -> None: ...


class WebAppLaunchHost(KioskLaunchHost, Protocol):
    def launch_webapp_server_now(self, launcher: str) -> None: ...


class VideoLaunchHost(RebootHost, Protocol):
    def launch_video_now(self, launcher: str) -> None: ...


class WebAppHost(UserHost, FileHost, PackageHost, WebAppLaunchHost, Protocol):
    def deploy_webapp(
        self,
        source: WebAppSource,
        progress: Callable[[str], None] | None = None,
    ) -> WebAppDeployment: ...

    def chromium_command(self) -> str | None: ...

    def wtype_command(self) -> str | None: ...

    def swayidle_command(self) -> str | None: ...


class VideoHost(UserHost, FileHost, PackageHost, VideoLaunchHost, Protocol):
    def deploy_video(
        self,
        source: VideoSource,
        progress: Callable[[str], None] | None = None,
    ) -> VideoDeployment: ...

    def mpv_command(self) -> str | None: ...

    def launch_video_now(self, launcher: str) -> None: ...


class RustDeskHost(Protocol):
    def install_rustdesk(
        self,
        password: str,
        progress: Callable[[str], None] | None = None,
    ) -> RustDeskInstall: ...

    def rustdesk_installed(self) -> bool: ...

    def configure_rustdesk_password(self, password: str) -> None: ...

    def connection_details(
        self,
        rustdesk_password: str | None = None,
    ) -> TotemConnectionDetails: ...


class TotemRegistrationHost(UserHost, RustDeskHost, Protocol):
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
    ) -> None: ...

    def install_totem_status_reporter(
        self,
        config: TotemStatusReporterConfig,
    ) -> str | None: ...


class Host(Protocol):
    """System port. Production talks to a Pi; tests use an in-memory fake."""

    def home(self) -> str: ...

    def user(self) -> str: ...

    def machine_name(self) -> str: ...

    def is_raspberry_pi(self) -> bool: ...

    def is_root(self) -> bool: ...

    def exists(self, path: str) -> bool: ...

    def mkdir(self, path: str) -> None: ...

    def read_file(self, path: str) -> str: ...

    def write_file(self, path: str, content: str) -> None: ...

    def detect_wayland_output(self) -> str | None: ...

    def run(self, argv: list[str], check: bool = True) -> object: ...

    def run_in_desktop_session(self, argv: list[str], check: bool = True) -> object: ...

    def deploy_webapp(
        self,
        source: WebAppSource,
        progress: Callable[[str], None] | None = None,
    ) -> WebAppDeployment: ...

    def deploy_video(
        self,
        source: VideoSource,
        progress: Callable[[str], None] | None = None,
    ) -> VideoDeployment: ...

    def chromium_command(self) -> str | None: ...

    def mpv_command(self) -> str | None: ...

    def wtype_command(self) -> str | None: ...

    def swayidle_command(self) -> str | None: ...

    def ensure_packages_installed(self, packages: tuple[str, ...]) -> None: ...

    def launch_kiosk_now(self, launcher: str) -> None: ...

    def launch_webapp_server_now(self, launcher: str) -> None: ...

    def launch_video_now(self, launcher: str) -> None: ...

    def reboot(self) -> None: ...

    def touchscreen_present(self) -> bool: ...

    def install_rustdesk(
        self,
        password: str,
        progress: Callable[[str], None] | None = None,
    ) -> RustDeskInstall: ...

    def rustdesk_installed(self) -> bool: ...

    def configure_rustdesk_password(self, password: str) -> None: ...

    def connection_details(
        self,
        rustdesk_password: str | None = None,
    ) -> TotemConnectionDetails: ...

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
    ) -> None: ...

    def install_totem_status_reporter(
        self,
        config: TotemStatusReporterConfig,
    ) -> str | None: ...

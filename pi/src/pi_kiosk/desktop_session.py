"""Ubuntu/Debian desktops: make labwc the autologin session, as on Raspberry Pi OS.

Everything else in the wizard (rotation, touch, kiosk autostart, cursor hide)
already targets labwc, so on a normal desktop it is enough to install labwc
and its Wayland tools and log the kiosk user straight into it.
"""

from __future__ import annotations

from pi_kiosk.errors import UserFacingError
from pi_kiosk.files import read_or_empty

LABWC_PACKAGES = ("labwc", "wlr-randr", "xwayland", "libinput-tools", "xdg-desktop-portal-wlr")
OPTIONAL_PACKAGES = ("wlopm",)
LABWC_SESSION = "labwc"
LABWC_SESSION_FILE = "/usr/share/wayland-sessions/labwc.desktop"
SLEEP_TARGETS = ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target")
GDM_CONFIG = "/etc/gdm3/custom.conf"
GDM_DEBIAN_CONFIG = "/etc/gdm3/daemon.conf"
ACCOUNTS_DIR = "/var/lib/AccountsService/users"
LIGHTDM_DROPIN = "/etc/lightdm/lightdm.conf.d/60-pi-kiosk.conf"


def set_ini_values(text: str, section: str, values: dict[str, str | None]) -> str:
    """Set (or, with None, remove) active keys in one INI section. Comments stay.

    Existing keys are replaced in place; new ones go right after the section
    header, before any commented examples.
    """
    lines = text.splitlines()
    header = f"[{section}]"
    if header not in (line.strip() for line in lines):
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(header)

    present = {_active_key(line) for line in _section_lines(lines, header)}
    out: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == header
            out.append(line)
            if in_section:
                out += [
                    f"{key}={value}"
                    for key, value in values.items()
                    if value is not None and key not in present
                ]
            continue
        key = _active_key(line) if in_section else None
        if key in values:
            if values[key] is not None:
                out.append(f"{key}={values[key]}")
            continue
        out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    return "\n".join(out) + "\n"


def _active_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", ";", "[")) or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()


def _section_lines(lines: list[str], header: str) -> list[str]:
    found: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == header
        elif in_section:
            found.append(line)
    return found


def install_labwc_session(host) -> None:
    host.run(["apt-get", "update"], check=True)
    host.run(["apt-get", "install", "-y", *LABWC_PACKAGES], check=True)
    # wlopm only adds a "screens on" guard at login; the kiosk works without it.
    host.run(["apt-get", "install", "-y", *OPTIONAL_PACKAGES], check=False)
    if not host.exists(LABWC_SESSION_FILE):
        raise UserFacingError(
            f"labwc was installed but {LABWC_SESSION_FILE} is missing, so it cannot be "
            "the login session. Install labwc manually and run the wizard again."
        )


def gdm_config_path(host) -> str:
    if not host.exists(GDM_CONFIG) and host.exists(GDM_DEBIAN_CONFIG):
        return GDM_DEBIAN_CONFIG
    return GDM_CONFIG


def enable_autologin(host, user: str, display_manager: str) -> str:
    """Returns a warning for the report, or an empty string."""
    if display_manager == "lightdm":
        host.mkdir(LIGHTDM_DROPIN.rsplit("/", 1)[0])
        host.write_file(
            LIGHTDM_DROPIN,
            "[Seat:*]\n"
            f"autologin-user={user}\n"
            f"autologin-session={LABWC_SESSION}\n"
            f"user-session={LABWC_SESSION}\n",
        )
        return ""

    path = gdm_config_path(host)
    config = read_or_empty(host, path)
    host.write_file(
        path,
        set_ini_values(config, "daemon", {"AutomaticLoginEnable": "True", "AutomaticLogin": user}),
    )
    accounts = f"{ACCOUNTS_DIR}/{user}"
    host.mkdir(ACCOUNTS_DIR)
    host.write_file(
        accounts,
        # A saved SessionType=x11 would make GDM look for labwc among Xorg sessions.
        set_ini_values(
            read_or_empty(host, accounts),
            "User",
            {"Session": LABWC_SESSION, "SessionType": "wayland"},
        ),
    )
    if _wayland_disabled(config):
        return (
            f"GDM has WaylandEnable=false in {path}, so it cannot start the labwc session. "
            "Remove that line (it is often set for NVIDIA cards) and reboot."
        )
    return ""


def disable_autologin(host, user: str, display_manager: str) -> None:
    if display_manager == "lightdm":
        host.remove_path(LIGHTDM_DROPIN)
        return
    path = gdm_config_path(host)
    config = read_or_empty(host, path)
    if config:
        host.write_file(path, set_ini_values(config, "daemon", {"AutomaticLoginEnable": "False"}))
    accounts = f"{ACCOUNTS_DIR}/{user}"
    current = read_or_empty(host, accounts)
    if f"Session={LABWC_SESSION}" in current:
        host.write_file(accounts, set_ini_values(current, "User", {"Session": None, "SessionType": None}))


def _wayland_disabled(config: str) -> bool:
    for line in config.splitlines():
        stripped = line.strip().replace(" ", "")
        if not stripped.startswith("#") and stripped.lower() == "waylandenable=false":
            return True
    return False

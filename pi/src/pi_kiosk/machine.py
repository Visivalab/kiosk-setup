"""Which kind of machine this is, and whether the tool may configure it.

Two platforms are supported:

- a Raspberry Pi with Raspberry Pi OS (labwc is already the desktop), and
- an Ubuntu/Debian desktop with GDM or LightDM, where labwc is installed and
  made the autologin session.

Servers (no display manager), WSL and containers are refused, so a run by
mistake on the machine that hosts this checkout still changes nothing.
"""

from __future__ import annotations

from pi_kiosk.detect import looks_like_raspberry_pi

RASPBERRY_PI = "raspberry-pi"
LINUX_DESKTOP = "linux-desktop"
UNSUPPORTED_MESSAGE = (
    "This tool only configures Raspberry Pi OS, or an Ubuntu/Debian desktop that "
    "uses GDM or LightDM. Nothing was changed on this machine."
)
_DISPLAY_MANAGERS = {"gdm": "gdm3", "gdm3": "gdm3", "lightdm": "lightdm"}


def parse_os_release(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.startswith("#"):
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def display_manager_from_unit(target: str | None) -> str | None:
    """`/etc/systemd/system/display-manager.service` points at the active one."""
    if not target:
        return None
    name = target.rstrip("/").rsplit("/", 1)[-1].removesuffix(".service")
    return _DISPLAY_MANAGERS.get(name)


def detect_platform(
    *,
    model: str | None,
    has_rpi_issue: bool,
    os_release: str,
    proc_version: str,
    display_manager: str | None,
    in_container: bool,
) -> str | None:
    if looks_like_raspberry_pi(model=model, has_rpi_issue=has_rpi_issue):
        return RASPBERRY_PI
    if "microsoft" in proc_version.lower() or in_container:
        return None
    release = parse_os_release(os_release)
    family = {release.get("ID", "")} | set(release.get("ID_LIKE", "").split())
    if not family & {"ubuntu", "debian"}:
        return None
    if display_manager is None:
        return None
    return LINUX_DESKTOP

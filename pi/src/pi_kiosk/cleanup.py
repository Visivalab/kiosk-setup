"""Undo what pi-kiosk configured, like the Windows "Remove kiosk setup" button.

Only tagged blocks and files owned by pi-kiosk are removed. Installed packages
(RustDesk, mpv, wtype, swayidle), the blanking setting and the remote
registration record are left alone.
"""

from __future__ import annotations

from typing import Callable

from pi_kiosk.files import read_or_empty
from pi_kiosk.host import WaylandOutput
from pi_kiosk.steps.kiosk_common import (
    CURSOR_RC_BEGIN,
    CURSOR_RC_END,
    KIOSK_AUTOSTART_BEGIN,
    KIOSK_AUTOSTART_END,
    LEGACY_CURSOR_AUTOSTART_BEGIN,
    LEGACY_CURSOR_AUTOSTART_END,
    LEGACY_WEBAPP_AUTOSTART_BEGIN,
    LEGACY_WEBAPP_AUTOSTART_END,
)
from pi_kiosk.steps.nosleep import BEGIN as NOSLEEP_BEGIN
from pi_kiosk.steps.nosleep import END as NOSLEEP_END
from pi_kiosk.steps.rotation import BEGIN as ROTATION_BEGIN
from pi_kiosk.steps.rotation import DEFAULT_OUTPUT, multi_display_command
from pi_kiosk.steps.rotation import END as ROTATION_END
from pi_kiosk.steps.touch import BEGIN as TOUCH_BEGIN
from pi_kiosk.steps.touch import END as TOUCH_END
from pi_kiosk.totem_status import (
    STATUS_SERVICE_NAME,
    STATUS_TIMER_NAME,
    status_script_path,
    status_service_path,
    status_timer_path,
)

AUTOSTART_BLOCKS = (
    (ROTATION_BEGIN, ROTATION_END),
    (NOSLEEP_BEGIN, NOSLEEP_END),
    (KIOSK_AUTOSTART_BEGIN, KIOSK_AUTOSTART_END),
    (LEGACY_WEBAPP_AUTOSTART_BEGIN, LEGACY_WEBAPP_AUTOSTART_END),
    (LEGACY_CURSOR_AUTOSTART_BEGIN, LEGACY_CURSOR_AUTOSTART_END),
)
RC_XML_BLOCKS = (
    (TOUCH_BEGIN, TOUCH_END),
    (CURSOR_RC_BEGIN, CURSOR_RC_END),
)


def run_cleanup(host, progress: Callable[[str], None] | None = None) -> list[str]:
    reports: list[str] = []

    def done(message: str) -> None:
        reports.append(f"Done: {message}")
        if progress is not None:
            progress(reports[-1])

    home = host.home()
    user = host.user()
    for pattern in (
        f"{home}/.config/pi-kiosk/",
        f"{home}/.local/share/pi-kiosk/",
        r"http\.server 8080 --bind 127\.0\.0\.1",
        r"chromium.*--kiosk.*127\.0\.0\.1:8080",
    ):
        host.run(["pkill", "-u", user, "-f", pattern], check=False)
    done("stopped the kiosk players, browser and local web server.")

    changed = _strip_blocks(host, f"{home}/.config/labwc/autostart", AUTOSTART_BLOCKS)
    changed += _strip_blocks(host, f"{home}/.config/labwc/rc.xml", RC_XML_BLOCKS)
    # labwc keeps the old touch calibration until it rereads rc.xml.
    host.run_in_desktop_session(["labwc", "--reconfigure"], check=False)
    done(f"removed {changed} pi-kiosk block(s) from the labwc autostart and rc.xml.")

    host.run(["systemctl", "disable", "--now", STATUS_TIMER_NAME], check=False)
    host.run(["systemctl", "stop", STATUS_SERVICE_NAME], check=False)
    for path in (status_timer_path(), status_service_path()):
        host.remove_path(str(path))
    host.run(["systemctl", "daemon-reload"], check=False)
    done("removed the totem status timer.")

    host.run(["raspi-config", "nonint", "do_boot_behaviour", "B3"], check=False)
    done("disabled desktop autologin; the desktop asks for the password again.")

    for path in (
        f"{home}/.config/pi-kiosk",
        f"{home}/.local/share/pi-kiosk",
        f"{home}/.local/state/pi-kiosk",
        "/etc/pi-kiosk",
        str(status_script_path().parent),
    ):
        host.remove_path(path)
    done("removed downloaded kiosk files, launchers, logs, and saved kiosk credentials.")

    outputs = host.detect_wayland_outputs() or [WaylandOutput(name=DEFAULT_OUTPUT)]
    # Positions are recalculated for landscape, or screens placed for portrait would overlap.
    argv = multi_display_command(outputs, {output.name: "none" for output in outputs})
    host.run_in_desktop_session(argv, check=False)
    done(f"restored normal rotation on {len(outputs)} display(s).")

    done(
        "Raspberry Pi kiosk cleanup completed. RustDesk, mpv, the blanking setting, "
        "and the remote registration were left unchanged."
    )
    return reports


def _strip_blocks(host, path: str, blocks) -> int:
    original = read_or_empty(host, path)
    if not original:
        return 0
    lines = original.splitlines(keepends=True)
    removed = 0
    for begin, end in blocks:
        lines, count = _remove_block_lines(lines, begin, end)
        removed += count
    updated = "".join(lines)
    if updated != original:
        host.write_file(path, updated)
    return removed


def _remove_block_lines(lines: list[str], begin: str, end: str) -> tuple[list[str], int]:
    """Drop whole lines from each begin marker through its end marker."""
    kept: list[str] = []
    inside = False
    count = 0
    for line in lines:
        if not inside and begin in line:
            inside = True
            count += 1
        if not inside:
            kept.append(line)
        elif end in line:
            inside = False
    return (lines, 0) if inside else (kept, count)

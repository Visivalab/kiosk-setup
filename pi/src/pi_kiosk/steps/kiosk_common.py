from __future__ import annotations

import shlex

from pi_kiosk.choice import Choice
from pi_kiosk.files import normalize_labwc_rc_xml, read_or_empty, upsert_marked_block
from pi_kiosk.host import Host

KIOSK_AUTOSTART_BEGIN = "# pi-kiosk-setup:kiosk-begin"
KIOSK_AUTOSTART_END = "# pi-kiosk-setup:kiosk-end"
LEGACY_WEBAPP_AUTOSTART_BEGIN = "# pi-kiosk-setup:webapp-kiosk-begin"
LEGACY_WEBAPP_AUTOSTART_END = "# pi-kiosk-setup:webapp-kiosk-end"
LEGACY_CURSOR_AUTOSTART_BEGIN = "# pi-kiosk-setup:cursor-hide-begin"
LEGACY_CURSOR_AUTOSTART_END = "# pi-kiosk-setup:cursor-hide-end"
CURSOR_RC_BEGIN = "<!-- pi-kiosk-setup:cursor-hide-begin -->"
CURSOR_RC_END = "<!-- pi-kiosk-setup:cursor-hide-end -->"
CURSOR_KEYBIND = "A-W-h"
NEXT_ACTION_PROMPT = "Choose what to do next."
SIMULATE_AUTORUN = "simulate"
REBOOT = "reboot"
CLOSE = "close"
NEXT_ACTION_CHOICES = [
    Choice(
        id=SIMULATE_AUTORUN,
        label="Simulate autorun - just for testing, cursor may not automatically hide",
    ),
    Choice(
        id=REBOOT,
        label="Reboot - More reliable, final production",
    ),
    Choice(
        id=CLOSE,
        label="Close - Keep the app server running on http://127.0.0.1:8080 without opening Chromium",
    ),
]


def remove_marked_block(original: str, begin: str, end: str) -> str:
    if begin not in original or end not in original:
        return original
    pre, rest = original.split(begin, 1)
    _, post = rest.split(end, 1)
    if post.startswith("\n"):
        post = post[1:]
    return pre + post


def install_kiosk_autostart(host: Host, launcher: str) -> None:
    home = host.home()
    autostart_path = f"{home}/.config/labwc/autostart"
    host.mkdir(f"{home}/.config/labwc")
    autostart = read_or_empty(host, autostart_path)
    for begin, end in (
        (LEGACY_CURSOR_AUTOSTART_BEGIN, LEGACY_CURSOR_AUTOSTART_END),
        (LEGACY_WEBAPP_AUTOSTART_BEGIN, LEGACY_WEBAPP_AUTOSTART_END),
        (KIOSK_AUTOSTART_BEGIN, KIOSK_AUTOSTART_END),
    ):
        autostart = remove_marked_block(autostart, begin, end)
    autostart = upsert_marked_block(
        autostart,
        KIOSK_AUTOSTART_BEGIN,
        KIOSK_AUTOSTART_END,
        f"bash {shlex.quote(launcher)}",
    )
    host.write_file(autostart_path, autostart)


def cursor_keybind_block(indent: str = "    ") -> str:
    action_indent = f"{indent}  "
    return "\n".join(
        [
            f"{indent}{CURSOR_RC_BEGIN}",
            f'{indent}<keybind key="{CURSOR_KEYBIND}">',
            f'{action_indent}<action name="WarpCursor" x="-1" y="-1" />',
            f'{action_indent}<action name="HideCursor" />',
            f"{indent}</keybind>",
            f"{indent}{CURSOR_RC_END}",
        ]
    )


def upsert_cursor_keybind(original: str) -> str:
    rc_xml_header = '<?xml version="1.0"?>\n<labwc_config>\n'
    rc_xml_footer = "</labwc_config>\n"
    original = normalize_labwc_rc_xml(original)
    block = cursor_keybind_block()
    keyboard_section = "\n".join(
        [
            "  <keyboard>",
            "    <default />",
            block,
            "  </keyboard>",
        ]
    )
    if not original.strip():
        return f"{rc_xml_header}{keyboard_section}\n{rc_xml_footer}"
    if CURSOR_RC_BEGIN in original and CURSOR_RC_END in original:
        pre, rest = original.split(CURSOR_RC_BEGIN, 1)
        _, post = rest.split(CURSOR_RC_END, 1)
        if post.startswith("\n"):
            post = post[1:]
        return f"{pre}{block}\n{post}"

    keyboard_self_closing = "  <keyboard />"
    if keyboard_self_closing in original:
        return original.replace(keyboard_self_closing, keyboard_section, 1)

    keyboard_close = "  </keyboard>"
    if keyboard_close in original:
        before, after = original.rsplit(keyboard_close, 1)
        if before and not before.endswith("\n"):
            before += "\n"
        return f"{before}{block}\n{keyboard_close}{after}"

    closing = "</labwc_config>"
    if closing in original:
        before, after = original.rsplit(closing, 1)
        if before and not before.endswith("\n"):
            before += "\n"
        return f"{before}{keyboard_section}\n{closing}{after}"

    if original and not original.endswith("\n"):
        original += "\n"
    return f"{original}{keyboard_section}\n"


def install_cursor_keybind(host: Host) -> None:
    path = f"{host.home()}/.config/labwc/rc.xml"
    host.write_file(path, upsert_cursor_keybind(read_or_empty(host, path)))

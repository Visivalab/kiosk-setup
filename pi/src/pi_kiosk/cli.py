from __future__ import annotations

import sys
from typing import TextIO

from pi_kiosk.app import NeedRoot, NotARaspberryPi, Wizard
from pi_kiosk.errors import UserFacingError
from pi_kiosk.host import Host
from pi_kiosk.linux import LinuxHost, NeedSudoUser
from pi_kiosk.terminal_ui import TerminalUI
from pi_kiosk.totem_registration import TotemRegistrar
from pi_kiosk.ui import UI


def main(
    argv: list[str] | None = None,
    host: Host | None = None,
    ui: UI | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    argv = [] if argv is None else list(argv)
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    real_host = host if host is not None else LinuxHost()
    real_ui = ui if ui is not None else TerminalUI()
    if argv:
        return _run_command(argv, real_host, real_ui, stdout=stdout, stderr=stderr)
    try:
        Wizard(real_host, real_ui).run()
    except KeyboardInterrupt:
        return 130
    except NotARaspberryPi as exc:
        print(str(exc), file=stderr)
        return 2
    except (EOFError, NeedRoot, NeedSudoUser, UserFacingError) as exc:
        if isinstance(exc, EOFError):
            print(
                "No terminal input was available for the wizard prompts. "
                "Run this tool from a real terminal. Nothing was changed.",
                file=stderr,
            )
            return 1
        print(str(exc), file=stderr)
        return 1
    return 0


def _run_command(
    argv: list[str],
    host: Host,
    ui: UI,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    command = argv[0]
    if command != "register-totem":
        print(f"Unknown command: {command}", file=stderr)
        return 1

    registrar = TotemRegistrar()
    try:
        if not host.is_raspberry_pi():
            raise NotARaspberryPi(
                "This tool only configures Raspberry Pi OS. "
                "Nothing was changed on this machine."
            )
        if not host.is_root():
            raise NeedRoot("Run this tool with sudo. Nothing was changed.")
        if registrar.config() is None:
            raise UserFacingError("Totem registration is not configured.")
        registration = registrar.ask(ui, host=host)
        report = registrar.register(host, registration, progress=ui.progress)
    except KeyboardInterrupt:
        return 130
    except NotARaspberryPi as exc:
        print(str(exc), file=stderr)
        return 2
    except (EOFError, NeedRoot, NeedSudoUser, UserFacingError) as exc:
        if isinstance(exc, EOFError):
            print(
                "No terminal input was available for the registration prompts. "
                "Run this tool from a real terminal. Nothing was changed.",
                file=stderr,
            )
            return 1
        print(str(exc), file=stderr)
        return 1

    print(report, file=stdout)
    return 0

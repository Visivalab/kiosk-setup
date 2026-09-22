from __future__ import annotations

import getpass
import sys
from typing import TextIO

from pi_kiosk.choice import Choice


class TerminalUI:
    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout

    def choose(self, prompt: str, options: list[Choice]) -> str:
        if not options:
            raise ValueError("choose() needs at least one option")

        while True:
            self.stdout.write(f"{prompt}\n")
            for index, option in enumerate(options, start=1):
                self.stdout.write(f"{index}) {option.label}\n")
            self.stdout.write(f"Choose [1-{len(options)}]: ")
            self.stdout.flush()

            raw = self.stdin.readline()
            if raw == "":
                raise EOFError("no rotation choice was provided")
            text = raw.strip()
            if text.isdigit():
                number = int(text)
                if 1 <= number <= len(options):
                    return options[number - 1].id
            self.stdout.write("Invalid choice. Enter a number from the list.\n")
            self.stdout.flush()

    def prompt(self, prompt: str) -> str:
        self.stdout.write(f"{prompt}: ")
        self.stdout.flush()
        raw = self.stdin.readline()
        if raw == "":
            raise EOFError("no text input was provided")
        return raw.strip()

    def secret(self, prompt: str) -> str:
        if self.stdin is sys.stdin:
            return getpass.getpass(f"{prompt}: ", stream=self.stdout)
        self.stdout.write(f"{prompt}: ")
        self.stdout.flush()
        raw = self.stdin.readline()
        if raw == "":
            raise EOFError("no secret input was provided")
        return raw.strip()

    def confirm(self, prompt: str, default: bool = True) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        while True:
            self.stdout.write(f"{prompt} {suffix}: ")
            self.stdout.flush()
            raw = self.stdin.readline()
            if raw == "":
                raise EOFError("no confirmation input was provided")
            text = raw.strip().lower()
            if text == "":
                return default
            if text in ("y", "yes"):
                return True
            if text in ("n", "no"):
                return False
            self.stdout.write("Invalid choice. Enter y or n.\n")
            self.stdout.flush()

    def progress(self, message: str) -> None:
        self.stdout.write(f"[....] {message}\n")
        self.stdout.flush()

    def info(self, message: str) -> None:
        self.stdout.write(f"{message}\n")
        self.stdout.flush()

    def warn(self, message: str) -> None:
        self.stdout.write(f"WARN: {message}\n")
        self.stdout.flush()

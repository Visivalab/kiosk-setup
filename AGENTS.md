# AGENTS.md — pi-kiosk-setup

Guidance for coding agents working in this repository.

## Scope and working copy

- Canonical checkout: `/home/gerard/projects/pi-kiosk-setup`
- Public GitHub remote: `https://github.com/Visivalab/kiosk-setup` (must be public for the curl one-liner). Do not push unless asked.
- This tool is meant to run on **other** Raspberry Pis, never on the VPS that hosts this checkout.
- Do not run `sudo ./kiosk.sh` or `python3 -m pi_kiosk` against a real host unless the user explicitly wants a live Pi configured. Tests use an in-memory fake.

## What this project does

Interactive first-boot wizard for Raspberry Pi OS Desktop (Bookworm / Trixie, labwc).

v1 asks one question (screen rotation), then always:

1. Writes a labwc `wlr-randr` rotation block
2. Disables screen blanking / sleep
3. Enables desktop autologin (`raspi-config` B4)

Autologin does not delete the account password. SSH and sudo still use it.

Not in v1: Chromium kiosk, touch remap, RustDesk. Those are extra steps, not a rewrite.

## Repository map

```text
kiosk.sh                       root pipeable entry point; runs the Pi subproject
setup.sh                       thin wrapper around kiosk.sh
pi/src/pi_kiosk/app.py         Pi wizard loop: ask → apply → report
pi/src/pi_kiosk/steps/         one Pi module per concern
pi/src/pi_kiosk/host.py        Pi Host protocol
pi/src/pi_kiosk/linux.py       only Pi code that touches a real machine
pi/src/pi_kiosk/terminal_ui.py numbered selector + Done: lines
pi/src/pi_kiosk/files.py       idempotent tagged-block edits
windows/                       future Windows subproject placeholder
tests/                         unittest, FakeHost / FakeUI
```

## Development rules

- Python 3 stdlib only. No pip, venv, or extra packages.
- TDD: failing test first for new behavior. `make test` must stay green.
- Add features as a new class in `pi/src/pi_kiosk/steps/` with `id`, `title`, `choices`, `ask()`, `apply()`. Register it in `default_steps()`.
- Do not put raspi-config or filesystem calls in the wizard. Steps talk to `Host`.
- Re-runs must be idempotent. User-facing files use `# pi-kiosk-setup:<name>-begin/end` blocks.
- Rotation names: `none` (0), `clockwise` (90), `counterclockwise` (270).
- Stay on Wayland/labwc. Do not switch the Pi back to X11.
- Do not commit, deploy, or configure a live Pi unless the user asks.
- `kiosk.sh` may be piped (`curl … | sudo bash`). Keep the body in `main()` so the script is fully read before stdin is reattached to `/dev/tty`. If `pi/src/pi_kiosk` is missing, it downloads the public GitHub archive.

## Safety

- Refuse non-Pi machines (`looks_like_raspberry_pi`).
- Refuse non-root.
- `LinuxHost` must write labwc files to the desktop user home (`SUDO_USER`), not `/root`.
- A live run on this VPS must exit 2 and change nothing.

## Verification

From the repository root:

```bash
make test
```

That is `python3 -m unittest discover -s tests -v`. Tests must never call real `raspi-config` or write `~/.config/labwc` on the machine that runs them.

After a behavior change, run `make test` and report the real result. Optional extra check: `PYTHONPATH=pi/src python3 -m pi_kiosk` on a non-Pi must print the refusal and exit 2.
